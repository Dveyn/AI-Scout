from __future__ import annotations

import logging

from scout.config import get_settings
from scout.runtime.daily_state import add_llm_cost, llm_spent_today

logger = logging.getLogger(__name__)


def can_spend_llm(estimated_rub: float = 0.0) -> bool:
    settings = get_settings()
    budget = settings.llm_daily_budget_rub
    if budget <= 0:
        return True
    spent = llm_spent_today()
    if spent + estimated_rub > budget:
        logger.warning("LLM budget exceeded: %.2f / %.2f ₽", spent, budget)
        return False
    return True


def record_llm_cost(amount: float) -> float:
    if amount <= 0:
        return llm_spent_today()
    total = add_llm_cost(amount)
    settings = get_settings()
    if settings.llm_daily_budget_rub > 0 and total >= settings.llm_daily_budget_rub * 0.8:
        logger.warning("LLM budget at %.0f%%: %.2f / %.2f ₽", 80, total, settings.llm_daily_budget_rub)
    return total
