from __future__ import annotations

import logging
from datetime import datetime

from office.bridge.scout_stats import get_kpi_snapshot
from office.config import get_office_settings
from office.models import DirectiveRecord, DirectiveStatus
from office.storage import db as office_db

logger = logging.getLogger(__name__)


async def run_directive_via_cursor(brief: str) -> DirectiveRecord:
    """Queue CEO task for Cursor Automation — result lands in verdicts/."""
    from scout.department.integrations import cursor_bridge

    settings = get_office_settings()
    directive = DirectiveRecord(brief=brief, status=DirectiveStatus.WAITING_CURSOR)
    await office_db.save_directive(directive)

    kpi = await get_kpi_snapshot()
    path = cursor_bridge.export_office_directive_handoff(
        directive.id,
        brief,
        kpi=kpi,
    )

    webhook_name = "office_directive"
    webhook_url = settings.cursor_webhook_office_directive.strip()
    if not webhook_url:
        webhook_name = "department_daily"
        webhook_url = settings.cursor_webhook_department_daily.strip()

    triggered = await cursor_bridge.trigger_cursor_webhook(
        webhook_name,
        {
            "type": "office_directive",
            "directive_id": directive.id,
            "file": path.name,
            "brief": brief[:500],
        },
    )

    plan = (
        "Задача отправлена в Cursor Automation. "
        f"Файл: scout/data/cursor/pending/{path.name}"
    )
    if not triggered:
        plan += (
            "\n\n⚠️ Webhook не сработал. Создайте automation из "
            ".cursor/automations/office-directive.yaml и добавьте "
            "CURSOR_WEBHOOK_OFFICE_DIRECTIVE в scout/.env — "
            "или откройте pending-файл в Cursor вручную."
        )

    await office_db.update_directive(
        directive.id,
        coo_plan=plan,
    )

    ingested = await cursor_bridge.apply_office_directive_verdicts()
    if ingested:
        updated = await office_db.get_directive(directive.id)
        if updated:
            return updated

    return await office_db.get_directive(directive.id) or directive


async def ingest_cursor_results() -> int:
    from scout.department.integrations import cursor_bridge

    return await cursor_bridge.apply_office_directive_verdicts()


async def run_directive_smart(brief: str) -> DirectiveRecord:
    """cursor → Cursor Automation; local/hybrid → локальный COO-граф."""
    settings = get_office_settings()
    use_cursor = settings.uses_cursor()
    if not use_cursor and settings.uses_hybrid():
        try:
            from scout.config import get_settings as scout_settings

            use_cursor = scout_settings().department_llm_provider.strip().lower() == "cursor"
        except Exception:
            pass
    if use_cursor:
        return await run_directive_via_cursor(brief)
    from office.orchestrator.directive import run_directive

    return await run_directive(brief)
