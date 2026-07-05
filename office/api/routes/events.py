from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from office.api.events import publish_event
from office.crews.secretary import scan_and_store_events
from office.storage import db as office_db

router = APIRouter(prefix="/api/online-events", tags=["online-events"])


class EventScanRequest(BaseModel):
    brief: str = Field(
        default="Собери онлайн-мероприятия для потенциальных клиентов B2B веб-студии",
        max_length=2000,
    )


class EventStatusUpdate(BaseModel):
    status: str = Field(pattern="^(new|reviewed|registered|skipped)$")


@router.get("")
async def list_events(status: str | None = None) -> dict:
    events = await office_db.list_online_events(limit=100, status=status)
    return {"events": [e.model_dump(mode="json") for e in events]}


@router.post("/scan")
async def scan_events(body: EventScanRequest) -> dict:
    publish_event("events_scan_started", {})
    result = await scan_and_store_events(brief=body.brief)
    publish_event("events_scan_done", {"saved": result.get("events_saved", 0)})
    return result


@router.patch("/{event_id}")
async def update_event(event_id: str, body: EventStatusUpdate) -> dict:
    ev = await office_db.update_online_event_status(event_id, body.status)
    if not ev:
        raise HTTPException(404, "Event not found")
    return {"event": ev.model_dump(mode="json")}
