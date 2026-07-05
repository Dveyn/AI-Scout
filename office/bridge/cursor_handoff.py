from __future__ import annotations

import logging
from typing import Any

from office.config import get_office_settings

logger = logging.getLogger(__name__)


async def export_heavy_work_to_cursor(
    work_type: str,
    payload: dict[str, Any],
) -> str | None:
    """Delegate heavy LLM work to Cursor when hybrid/cursor mode."""
    settings = get_office_settings()
    if not settings.uses_hybrid() and not settings.uses_cursor():
        return None
    try:
        from scout.department.integrations import cursor_bridge

        if work_type == "department_daily":
            from scout.department.kpi import build_report_without_llm
            from scout.storage import department_db as dept_db

            report = await build_report_without_llm()
            deals = await dept_db.list_deals(limit=20)
            path = cursor_bridge.export_department_cycle_handoff(report, deals)
            await cursor_bridge.trigger_cursor_webhook(
                "department_daily",
                {"type": "department_daily", "file": path.name},
            )
            return path.name
        if work_type == "marketing_task":
            path = cursor_bridge.PENDING_DIR / f"office-task-{payload.get('task_id', 'unknown')}.json"
            import json

            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            await cursor_bridge.trigger_cursor_webhook(
                "department_daily",
                {"type": "office_marketing_task", "file": path.name},
            )
            return path.name
    except Exception as exc:
        logger.warning("Cursor handoff failed: %s", exc)
    return None


async def apply_cursor_verdicts() -> int:
    try:
        from scout.department.integrations.cursor_bridge import apply_verdicts_from_files

        return await apply_verdicts_from_files()
    except Exception as exc:
        logger.warning("apply_verdicts failed: %s", exc)
        return 0
