from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from scout.agent.cost_guard import can_spend_llm, record_llm_cost
from scout.department.skills_bridge import load_department_skill
from scout.llm.client import GPTunnelClient
from scout.storage import department_db as db

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "agents" / "prompts"

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_result",
        "description": "Submit structured agent result",
        "parameters": {
            "type": "object",
            "properties": {
                "result": {
                    "type": "object",
                    "description": "Agent output as JSON object",
                },
                "summary": {
                    "type": "string",
                    "description": "Short human-readable summary",
                },
            },
            "required": ["result", "summary"],
        },
    },
}


class BaseAgent:
    """Unified LLM agent with skills injection and structured output."""

    agent_name: str = "base"
    max_rounds: int = 2

    def __init__(self) -> None:
        self.llm = GPTunnelClient()
        self._skill_text = load_department_skill(self.agent_name)

    def _system_prompt(self) -> str:
        prompt_path = PROMPTS_DIR / f"{self.agent_name}.ru.md"
        template = (
            prompt_path.read_text(encoding="utf-8")
            if prompt_path.is_file()
            else f"You are AI {self.agent_name.upper()} for a B2B web studio."
        )
        return template.replace("{skill}", self._skill_text)

    async def run(
        self,
        user_message: str,
        *,
        action: str = "run",
        result_schema_hint: str = "",
    ) -> tuple[dict[str, Any], str, float]:
        if not can_spend_llm():
            logger.warning("LLM budget exceeded, %s skipped", self.agent_name)
            return {}, "LLM budget exceeded", 0.0

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": user_message
                + (f"\n\nExpected result shape:\n{result_schema_hint}" if result_schema_hint else ""),
            },
        ]
        total_cost = 0.0
        result: dict[str, Any] = {}
        summary = ""

        for round_num in range(1, self.max_rounds + 1):
            force = round_num == self.max_rounds
            response = await self.llm.chat(
                messages=messages,
                tools=[SUBMIT_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_result"}}
                if force
                else "auto",
            )
            total_cost += response.cost_rub
            record_llm_cost(response.cost_rub)

            if not response.tool_calls:
                if response.content:
                    try:
                        result = json.loads(response.content)
                        summary = result.get("summary", response.content[:200])
                    except json.JSONDecodeError:
                        summary = response.content[:500]
                if force:
                    break
                messages.append({"role": "user", "content": "Call submit_result with your output."})
                continue

            for tc in response.tool_calls:
                if tc["name"] != "submit_result":
                    continue
                try:
                    args = json.loads(tc["arguments"])
                    result = args.get("result", {})
                    summary = args.get("summary", "")
                except json.JSONDecodeError:
                    summary = "parse error"
                break
            break

        await db.log_agent_action(
            agent=self.agent_name,
            action=action,
            input_preview=user_message[:300],
            output_preview=summary[:500],
            cost_rub=total_cost,
        )
        return result, summary, total_cost
