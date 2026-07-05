from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from office.api.events import publish_event
from office.config import get_office_settings
from office.orchestrator.directive_router import ingest_cursor_results, run_directive_smart
from office.storage import db as office_db

router = APIRouter(prefix="/api/directives", tags=["directives"])


class DirectiveCreate(BaseModel):
    brief: str = Field(min_length=5, max_length=4000)


@router.get("/mode")
async def directive_mode() -> dict:
    settings = get_office_settings()
    use_cursor = settings.uses_cursor()
    if not use_cursor and settings.uses_hybrid():
        try:
            from scout.config import get_settings as scout_settings

            use_cursor = scout_settings().department_llm_provider.strip().lower() == "cursor"
        except Exception:
            pass
    return {
        "mode": "cursor" if use_cursor else "local",
        "hint": (
            "Задача уходит в Cursor Automation (подписка). Результат появится после verdict."
            if use_cursor
            else "Задача выполняется локально через GPTunnel."
        ),
    }


@router.post("/ingest")
async def ingest_directives() -> dict:
    n = await ingest_cursor_results()
    return {"imported": n}


@router.get("")
async def list_directives() -> dict:
    items = await office_db.list_directives(limit=30)
    return {"directives": [d.model_dump(mode="json") for d in items]}


@router.get("/{directive_id}")
async def get_directive(directive_id: str) -> dict:
    d = await office_db.get_directive(directive_id)
    if not d:
        raise HTTPException(404, "Directive not found")
    return {"directive": d.model_dump(mode="json")}


@router.post("")
async def create_directive(body: DirectiveCreate) -> dict:
    publish_event("directive_started", {"brief": body.brief[:120]})
    try:
        result = await run_directive_smart(body.brief)
    except Exception as exc:
        raise HTTPException(503, f"Не удалось выполнить поручение: {exc}") from exc
    if result.status.value == "completed":
        publish_event("directive_completed", {"directive_id": result.id})
    else:
        publish_event("directive_queued", {"directive_id": result.id})
    return {"directive": result.model_dump(mode="json")}
