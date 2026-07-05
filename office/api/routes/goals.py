from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from office.api.events import publish_event
from office.models import GoalHorizon, GoalRecord, GoalStatus
from office.orchestrator.goal_cascade import run_goal_cascade
from office.storage import db as office_db

router = APIRouter(prefix="/api/goals", tags=["goals"])


class GoalCreate(BaseModel):
    horizon: GoalHorizon
    text: str = Field(min_length=3, max_length=2000)
    owner_department: str = ""


@router.get("")
async def list_goals(horizon: GoalHorizon | None = None) -> dict:
    goals = await office_db.list_goals(horizon=horizon)
    return {"goals": [g.model_dump(mode="json") for g in goals]}


@router.post("")
async def create_goal(body: GoalCreate) -> dict:
    goal = GoalRecord(
        horizon=body.horizon,
        text=body.text,
        owner_department=body.owner_department,
        status=GoalStatus.ACTIVE,
    )
    saved = await office_db.save_goal(goal)
    publish_event("goal_created", {"goal_id": saved.id})
    return {"goal": saved.model_dump(mode="json")}


@router.post("/{goal_id}/cascade")
async def cascade_goal(goal_id: str) -> dict:
    goals = await office_db.list_goals()
    parent = next((g for g in goals if g.id == goal_id), None)
    if not parent:
        raise HTTPException(404, "Goal not found")
    result = await run_goal_cascade(parent)
    publish_event("goal_cascaded", {"goal_id": goal_id, "children": len(result.child_goals)})
    return result.model_dump(mode="json")
