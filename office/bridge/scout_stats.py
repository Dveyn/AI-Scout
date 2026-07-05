from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_scout_dashboard_stats() -> dict[str, Any]:
    try:
        from scout.storage import db as scout_db

        stats = await scout_db.get_dashboard_stats()
        return {
            "total_jobs": stats.total_jobs,
            "total_leads": stats.total_leads,
            "targets": stats.total_targets,
            "emails_sent": stats.emails_sent,
            "llm_cost_rub": stats.total_llm_cost_rub,
        }
    except Exception as exc:
        logger.warning("scout stats unavailable: %s", exc)
        return {}


async def get_department_stats() -> dict[str, Any]:
    try:
        from scout.storage import department_db as dept_db

        return await dept_db.get_department_stats()
    except Exception as exc:
        logger.warning("department stats unavailable: %s", exc)
        return {}


async def get_kpi_snapshot() -> dict[str, Any]:
    try:
        from scout.department.kpi import build_kpi_snapshot

        kpi = await build_kpi_snapshot()
        return kpi.model_dump()
    except Exception as exc:
        logger.warning("kpi unavailable: %s", exc)
        return {}
