from __future__ import annotations

import json
import logging
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from office.bridge.department_tasks import create_department_task
from office.llm import OfficeLLMClient, can_spend_office
from office.models import GoalCascadeResult, GoalHorizon, GoalRecord, GoalStatus, ModelTier
from office.storage import db as office_db

logger = logging.getLogger(__name__)

HORIZON_CHILD_MAP = {
    GoalHorizon.MONTH: GoalHorizon.WEEK,
    GoalHorizon.WEEK: GoalHorizon.DAY,
    GoalHorizon.DAY: None,
}


class GoalState(TypedDict):
    parent_goal: dict[str, Any]
    child_goals: Annotated[list[dict[str, Any]], operator.add]
    department_tasks: Annotated[list[dict[str, Any]], operator.add]
    coo_plan: str
    cost_rub: float
    error: str


async def _load_parent(state: GoalState) -> GoalState:
    return state


async def _coo_decompose(state: GoalState) -> GoalState:
    parent = GoalRecord.model_validate(state["parent_goal"])
    child_horizon = HORIZON_CHILD_MAP.get(parent.horizon)
    if child_horizon is None:
        return {**state, "coo_plan": "Дневная цель — исполняется напрямую."}

    if not await can_spend_office(department="executive"):
        return {**state, "error": "Бюджет исчерпан", "coo_plan": ""}

    llm = OfficeLLMClient()
    prompt = f"""Декомпозируй цель CEO на подцели горизонта «{child_horizon.value}».

Цель ({parent.horizon.value}): {parent.text}

Верни JSON:
{{
  "summary": "краткий план",
  "children": [
    {{"department": "marketing|sales|leadgen|production", "text": "подцель"}}
  ]
}}"""
    resp = await llm.complete("COO", prompt, tier=ModelTier.STRATEGY, department="executive")
    children: list[dict[str, Any]] = []
    summary = resp.content
    try:
        start = resp.content.find("{")
        end = resp.content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(resp.content[start:end])
            summary = parsed.get("summary", summary)
            children = parsed.get("children", [])
    except json.JSONDecodeError:
        children = [{"department": "marketing", "text": parent.text}]

    child_records: list[dict[str, Any]] = []
    for item in children[:5]:
        child = GoalRecord(
            horizon=child_horizon,
            text=item.get("text", parent.text),
            owner_department=item.get("department", ""),
            parent_goal_id=parent.id,
            status=GoalStatus.ACTIVE,
        )
        saved = await office_db.save_goal(child)
        child_records.append(saved.model_dump(mode="json"))

    return {
        **state,
        "child_goals": child_records,
        "coo_plan": summary,
        "cost_rub": state.get("cost_rub", 0.0) + resp.cost_rub,
    }


async def _assign_tasks(state: GoalState) -> GoalState:
    if state.get("error"):
        return state
    tasks: list[dict[str, Any]] = []
    for child_raw in state.get("child_goals", []):
        dept = child_raw.get("owner_department") or "marketing"
        agent_key = {
            "marketing": "smm",
            "sales": "sales",
            "leadgen": "scout",
            "production": "pm",
        }.get(dept, "cmo")
        task = await create_department_task(
            agent_key=agent_key,
            task_type="office_goal_cascade",
            brief=child_raw.get("text", ""),
            priority=7,
            requires_approval=dept in ("marketing", "sales"),
            input_json={"goal_id": child_raw.get("id"), "department": dept},
        )
        tasks.append(task.model_dump(mode="json"))
    return {**state, "department_tasks": tasks}


def build_goal_graph():
    graph = StateGraph(GoalState)
    graph.add_node("load", _load_parent)
    graph.add_node("decompose", _coo_decompose)
    graph.add_node("assign", _assign_tasks)
    graph.set_entry_point("load")
    graph.add_edge("load", "decompose")
    graph.add_edge("decompose", "assign")
    graph.add_edge("assign", END)
    return graph.compile()


async def run_goal_cascade(goal: GoalRecord) -> GoalCascadeResult:
    app = build_goal_graph()
    initial: GoalState = {
        "parent_goal": goal.model_dump(mode="json"),
        "child_goals": [],
        "department_tasks": [],
        "coo_plan": "",
        "cost_rub": 0.0,
        "error": "",
    }
    final = await app.ainvoke(initial)
    parent = GoalRecord.model_validate(final["parent_goal"])
    children = [GoalRecord.model_validate(c) for c in final.get("child_goals", [])]
    return GoalCascadeResult(
        parent_goal=parent,
        child_goals=children,
        department_tasks=final.get("department_tasks", []),
        cost_rub=final.get("cost_rub", 0.0),
        summary=final.get("coo_plan", "") or final.get("error", ""),
    )
