from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from office.api.events import publish_event
from office.crews.marketing import execute_marketing_brief, run_marketing_crew
from office.orchestrator.standup_meeting import run_standup
from office.storage import db as office_db

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class StandupRequest(BaseModel):
    agenda: str = ""


class MarketingBriefRequest(BaseModel):
    brief: str


@router.get("")
async def list_meetings() -> dict:
    meetings = await office_db.list_meetings()
    return {"meetings": [m.model_dump(mode="json") for m in meetings]}


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str) -> dict:
    meeting = await office_db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    items = await office_db.list_meeting_items(meeting_id)
    return {
        "meeting": meeting.model_dump(mode="json"),
        "items": [i.model_dump(mode="json") for i in items],
    }


@router.post("/standup")
async def start_standup(body: StandupRequest) -> dict:
    import logging

    logger = logging.getLogger(__name__)
    publish_event("standup_started", {})
    try:
        result = await run_standup(agenda=body.agenda)
    except Exception as exc:
        logger.exception("standup endpoint failed")
        raise HTTPException(
            status_code=503,
            detail=f"Совещание не удалось: {exc}",
        ) from exc
    publish_event("standup_completed", {"meeting_id": result.meeting.id})
    out = result.model_dump(mode="json")
    out["mode"] = "local" if result.cost_rub == 0 and "локальн" in (result.coo_synthesis or "").lower() else "llm"
    return out


@router.post("/marketing-crew")
async def marketing_crew_endpoint(body: MarketingBriefRequest) -> dict:
    result = await run_marketing_crew(body.brief)
    publish_event("marketing_crew_done", result)
    return result
