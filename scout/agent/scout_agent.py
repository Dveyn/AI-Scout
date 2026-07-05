from __future__ import annotations

import json
from pathlib import Path

from scout.agent.tools import (
    SUBMIT_ONLY_TOOL_DEFINITIONS,
    TOOL_DEFINITIONS,
    build_user_message,
    dispatch_tool,
    preview_tool_result,
)
from scout.agent.skills.loader import load_skill
from scout.company import COMPANY_NAME, COMPANY_SITE
from scout.config import get_settings
from scout.llm.client import GPTunnelClient
from scout.models.contacts import LeadContacts
from scout.models.schemas import AgentResult, AgentTraceStep, ProcessedLead, RawLead, Tone


class ScoutAgent:
    def __init__(self, skill_name: str | None = None) -> None:
        self.settings = get_settings()
        self.llm = GPTunnelClient()
        self._system_template = (
            Path(__file__).parent / "prompts" / "system.ru.md"
        ).read_text(encoding="utf-8")
        self._skill_name = skill_name or self.settings.agent_skill
        self._skill_text = load_skill(self._skill_name)

    def _system_prompt(self, icp: str, product: str, tone: Tone) -> str:
        return self._system_template.format(
            company_name=COMPANY_NAME,
            company_site=COMPANY_SITE,
            icp=icp,
            product=product,
            tone=tone.value,
            fit_threshold=self.settings.fit_score_threshold,
            skill=self._skill_text,
        )

    async def process_lead(
        self,
        lead: RawLead,
        icp: str,
        product: str,
        tone: Tone = Tone.BUSINESS,
        website_audit: dict | None = None,
        preflight_trace: list[AgentTraceStep] | None = None,
        contacts: LeadContacts | None = None,
    ) -> ProcessedLead:
        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt(icp, product, tone)},
            {"role": "user", "content": build_user_message(lead, website_audit, contacts)},
        ]
        trace: list[AgentTraceStep] = list(preflight_trace or [])
        total_cost = 0.0
        tool_calls_used = 0
        final_result: AgentResult | None = None

        for round_num in range(1, self.settings.agent_max_rounds + 1):
            force_submit = (
                round_num == self.settings.agent_max_rounds
                or tool_calls_used >= self.settings.agent_max_tool_calls
            )

            response = await self.llm.chat(
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice={"type": "function", "function": {"name": "submit_lead_result"}}
                if force_submit
                else "auto",
            )
            total_cost += response.cost_rub

            if response.content:
                trace.append(
                    AgentTraceStep(
                        round=round_num,
                        type="assistant_text",
                        content=response.content[:500],
                    )
                )

            if not response.tool_calls:
                if force_submit:
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": "Заверши работу вызовом submit_lead_result.",
                    }
                )
                continue

            assistant_tool_calls = []
            for tc in response.tool_calls:
                assistant_tool_calls.append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": assistant_tool_calls,
                }
            )

            for tc in response.tool_calls:
                name = tc["name"]
                try:
                    args = json.loads(tc["arguments"])
                except json.JSONDecodeError:
                    args = {}

                if name != "submit_lead_result":
                    tool_calls_used += 1

                result, terminal = await dispatch_tool(name, args)
                preview = preview_tool_result(result)

                trace.append(
                    AgentTraceStep(
                        round=round_num,
                        type="tool_call",
                        content=f"Вызов {name}",
                        tool_name=name,
                        tool_args=args,
                        tool_result_preview=preview,
                    )
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

                if terminal is not None:
                    final_result = self._apply_threshold(terminal)
                    trace.append(
                        AgentTraceStep(
                            round=round_num,
                            type="submit",
                            content=final_result.reasoning_summary,
                        )
                    )
                    return ProcessedLead(
                        raw=lead,
                        result=final_result,
                        trace=trace,
                        llm_cost_rub=total_cost,
                    )

                if tool_calls_used >= self.settings.agent_max_tool_calls:
                    break

        if final_result is None:
            final_result = self._fallback_result(lead)
            trace.append(
                AgentTraceStep(
                    round=self.settings.agent_max_rounds,
                    type="fallback",
                    content="Агент не завершил работу — применён fallback.",
                )
            )

        return ProcessedLead(
            raw=lead,
            result=final_result,
            trace=trace,
            llm_cost_rub=total_cost,
        )

    async def process_lead_lite(
        self,
        lead: RawLead,
        icp: str,
        product: str,
        tone: Tone = Tone.BUSINESS,
        website_audit: dict | None = None,
        preflight_trace: list[AgentTraceStep] | None = None,
        contacts: LeadContacts | None = None,
        website_content: dict | None = None,
    ) -> ProcessedLead:
        """Один вызов LLM без tool-loop — ~3× дешевле полного агента."""
        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt(icp, product, tone)},
            {
                "role": "user",
                "content": build_user_message(
                    lead,
                    website_audit,
                    contacts,
                    website_content,
                    lite=True,
                ),
            },
        ]
        trace: list[AgentTraceStep] = list(preflight_trace or [])
        trace.append(
            AgentTraceStep(round=1, type="mode", content="lite — один вызов LLM")
        )

        response = await self.llm.chat(
            messages=messages,
            tools=SUBMIT_ONLY_TOOL_DEFINITIONS,
            tool_choice={"type": "function", "function": {"name": "submit_lead_result"}},
        )
        total_cost = response.cost_rub

        if not response.tool_calls:
            final_result = self._fallback_result(lead)
            return ProcessedLead(raw=lead, result=final_result, trace=trace, llm_cost_rub=total_cost)

        tc = response.tool_calls[0]
        try:
            args = json.loads(tc["arguments"])
        except json.JSONDecodeError:
            args = {}

        _, terminal = await dispatch_tool(tc["name"], args)
        if terminal is None:
            final_result = self._fallback_result(lead)
        else:
            final_result = self._apply_threshold(terminal)
            trace.append(
                AgentTraceStep(
                    round=1,
                    type="submit",
                    content=final_result.reasoning_summary,
                )
            )

        return ProcessedLead(
            raw=lead,
            result=final_result,
            trace=trace,
            llm_cost_rub=total_cost,
        )

    def _apply_threshold(self, result: AgentResult) -> AgentResult:
        threshold = self.settings.fit_score_threshold
        if not result.is_target or result.fit_score < threshold:
            return result.model_copy(
                update={"subject": None, "message": None},
            )
        return result

    def _fallback_result(self, lead: RawLead) -> AgentResult:
        return AgentResult(
            fit_score=0,
            is_target=False,
            reason=f"Не удалось обработать лид «{lead.name}» — недостаточно данных или ошибка агента.",
            pains=[],
            hook="",
            product_angle="",
            subject=None,
            message=None,
            channel_hint="email" if lead.email else ("phone" if lead.phone else "email"),
            reasoning_summary="Агент исчерпал лимит раундов без submit_lead_result.",
            website_issues=[],
        )
