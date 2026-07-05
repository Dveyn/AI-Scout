from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from office.api.events import publish_event
from office.crews.marketing import run_workstation_task
from office.registry.agents import create_workstation_from_preset
from office.storage import db as office_db

router = APIRouter(prefix="/api/workstations", tags=["workstations"])


class WorkstationCreate(BaseModel):
    preset_id: str
    name: str = ""
    custom_prompt: str = ""


class WorkstationTask(BaseModel):
    brief: str = Field(min_length=3, max_length=4000)


@router.get("")
async def list_workstations() -> dict:
    items = await office_db.list_workstations()
    return {"workstations": [w.model_dump(mode="json") for w in items]}


@router.post("")
async def create_workstation(body: WorkstationCreate) -> dict:
    try:
        ws = await create_workstation_from_preset(
            body.preset_id,
            name=body.name or None,
            custom_prompt=body.custom_prompt,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    publish_event("workstation_created", {"id": ws.id, "role": ws.role})
    return {"workstation": ws.model_dump(mode="json")}


@router.get("/{workstation_id}/activity")
async def workstation_activity(workstation_id: str) -> dict:
    ws = await office_db.get_workstation(workstation_id)
    if not ws:
        raise HTTPException(404, "Workstation not found")
    activity = await office_db.list_activity(workstation_id)
    return {
        "workstation": ws.model_dump(mode="json"),
        "activity": [a.model_dump(mode="json") for a in activity],
    }


@router.post("/{workstation_id}/run")
async def run_task(workstation_id: str, body: WorkstationTask) -> dict:
    ws = await office_db.get_workstation(workstation_id)
    if not ws:
        raise HTTPException(404, "Workstation not found")
    publish_event("workstation_working", {"id": workstation_id})
    try:
        result = await run_workstation_task(workstation_id, body.brief)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.get("error"):
        publish_event("workstation_error", {"id": workstation_id, "error": result["error"]})
    else:
        publish_event("workstation_done", {"id": workstation_id, "result": result})
    return result
