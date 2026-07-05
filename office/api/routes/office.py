from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from office.api.events import publish_event
from office.bridge import (
    get_department_stats,
    get_scout_dashboard_stats,
    list_active_tasks,
    list_recent_agent_logs,
)
from office.crews.loader import load_presets
from office.llm import budget_snapshot
from office.models import GoalHorizon, GoalRecord, GoalStatus, OfficeOverview
from office.registry.agents import (
    create_workstation_from_preset,
    registry_summary,
    seed_default_assistants,
    seed_default_heads,
)
from office.storage import db as office_db

router = APIRouter(prefix="/api/office", tags=["office"])


@router.get("/overview", response_model=OfficeOverview)
async def overview() -> OfficeOverview:
    await seed_default_heads()
    await seed_default_assistants()
    budget = await office_db.get_global_budget()
    return OfficeOverview(
        departments=await office_db.list_departments(),
        workstations=await office_db.list_workstations(),
        goals=await office_db.list_goals(),
        active_meetings=[
            m for m in await office_db.list_meetings(limit=5) if m.status.value != "cancelled"
        ],
        budget_global=budget,
        scout_stats=await get_scout_dashboard_stats(),
        department_stats=await get_department_stats(),
    )


@router.get("/registry")
async def registry() -> dict:
    return {
        "registry": registry_summary(),
        "presets": {k: v.model_dump() for k, v in load_presets().items()},
    }


@router.get("/tasks")
async def tasks() -> dict:
    return {
        "department_tasks": [t.model_dump(mode="json") for t in await list_active_tasks()],
        "agent_logs": await list_recent_agent_logs(limit=30),
    }


@router.get("/budget")
async def budget() -> dict:
    return await budget_snapshot()
