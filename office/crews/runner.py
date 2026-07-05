from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from office.llm import OfficeLLMClient, can_spend_office, record_office_cost
from office.models import ModelTier

logger = logging.getLogger(__name__)

AgentFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class CrewAgent:
    role: str
    goal: str
    backstory: str = ""
    tier: ModelTier = ModelTier.EXECUTION
    department: str = ""
    handler: AgentFn | None = None


@dataclass
class CrewTask:
    description: str
    agent: CrewAgent
    context_keys: list[str] = field(default_factory=list)


@dataclass
class CrewResult:
    outputs: list[dict[str, Any]] = field(default_factory=list)
    total_cost_rub: float = 0.0
    summary: str = ""


class CrewRunner:
    """CrewAI-compatible sequential crew without external crewai dependency."""

    def __init__(self, agents: list[CrewAgent], tasks: list[CrewTask]) -> None:
        self.agents = {a.role: a for a in agents}
        self.tasks = tasks

    async def kickoff(self, inputs: dict[str, Any] | None = None) -> CrewResult:
        state = dict(inputs or {})
        outputs: list[dict[str, Any]] = []
        total_cost = 0.0

        for task in self.tasks:
            agent = task.agent
            if not await can_spend_office(department=agent.department):
                outputs.append({"role": agent.role, "error": "budget exceeded"})
                break

            context_parts = [state.get(k, "") for k in task.context_keys if state.get(k)]
            context = "\n".join(str(c) for c in context_parts if c)
            prompt = f"{task.description}\n\nКонтекст:\n{context}" if context else task.description

            if agent.handler:
                result = await agent.handler(prompt, state)
                total_cost += float(result.get("cost_rub", 0))
                outputs.append({"role": agent.role, **result})
                state[f"{agent.role}_output"] = result.get("summary", "")
                continue

            llm = OfficeLLMClient()
            full_prompt = f"Цель: {agent.goal}\n\n{prompt}"
            if agent.backstory:
                full_prompt = f"{agent.backstory}\n\n{full_prompt}"
            resp = await llm.complete(
                agent.role,
                full_prompt,
                tier=agent.tier,
                department=agent.department,
            )
            total_cost += resp.cost_rub
            outputs.append({"role": agent.role, "summary": resp.content, "cost_rub": resp.cost_rub})
            state[f"{agent.role}_output"] = resp.content

        summary = outputs[-1].get("summary", "") if outputs else ""
        return CrewResult(outputs=outputs, total_cost_rub=total_cost, summary=summary)
