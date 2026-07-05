from __future__ import annotations

import logging

from office.config import get_office_settings
from office.models import ModelTier
from office.storage import db as office_db

logger = logging.getLogger(__name__)


async def can_spend_office(
    estimated_rub: float = 0.0,
    *,
    department: str = "",
) -> bool:
    settings = get_office_settings()
    await office_db.reset_daily_budget_if_needed()
    global_budget = await office_db.get_global_budget()
    if global_budget.limit_rub > 0 and global_budget.spent_rub + estimated_rub > global_budget.limit_rub:
        logger.warning(
            "Office global budget exceeded: %.2f / %.2f ₽",
            global_budget.spent_rub,
            global_budget.limit_rub,
        )
        return False
    if department and settings.office_dept_budget_rub > 0:
        dept_budgets = await _dept_spent(department)
        if dept_budgets + estimated_rub > settings.office_dept_budget_rub:
            logger.warning("Dept %s budget exceeded: %.2f", department, dept_budgets)
            return False
    # Also respect scout cost guard
    try:
        from scout.agent.cost_guard import can_spend_llm

        return can_spend_llm(estimated_rub)
    except Exception:
        return True


async def record_office_cost(
    amount: float,
    *,
    department: str = "",
) -> None:
    if amount <= 0:
        return
    await office_db.add_budget_spend(amount, scope="global")
    if department:
        await office_db.add_budget_spend(amount, scope="department", scope_id=department)
    try:
        from scout.agent.cost_guard import record_llm_cost

        record_llm_cost(amount)
    except Exception:
        pass


async def _dept_spent(department: str) -> float:
    from office.storage.db import _db_path
    import aiosqlite

    async with aiosqlite.connect(_db_path()) as conn:
        row = await (
            await conn.execute(
                "SELECT spent_rub FROM office_budget WHERE scope = 'department' AND scope_id = ?",
                (department,),
            )
        ).fetchone()
    return float(row[0]) if row else 0.0


async def budget_snapshot() -> dict:
    await office_db.reset_daily_budget_if_needed()
    global_b = await office_db.get_global_budget()
    settings = get_office_settings()
    scout_cost = 0.0
    try:
        from scout.runtime.daily_state import llm_spent_today

        scout_cost = llm_spent_today()
    except Exception:
        pass
    return {
        "global_limit_rub": global_b.limit_rub,
        "global_spent_rub": global_b.spent_rub,
        "dept_limit_rub": settings.office_dept_budget_rub,
        "scout_spent_rub": scout_cost,
        "provider": settings.office_llm_provider,
    }
