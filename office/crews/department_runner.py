from __future__ import annotations

import logging
from typing import Any

from office.bridge.scout_stats import get_department_stats, get_kpi_snapshot
from office.crews.loader import head_preset_for_department
from office.crews.marketing import execute_marketing_brief
from office.llm import OfficeLLMClient, OfficeLLMError, can_spend_office
from office.models import ModelTier
from office.registry.prompts import build_agent_system_prompt
from office.storage import db as office_db

logger = logging.getLogger(__name__)

DEPT_LABELS = {
    "marketing": "Маркетинг",
    "sales": "Продажи",
    "leadgen": "Лидоген",
    "production": "Продакшн",
}


async def execute_department_brief(
    department: str,
    brief: str,
    *,
    start_at: str = "",
    deadline: str = "",
) -> dict[str, Any]:
    """Run a sub-task for one department head (real execution, not just a plan)."""
    dept = department.lower().strip()
    label = DEPT_LABELS.get(dept, dept)
    preset = head_preset_for_department(dept)
    schedule_note = ""
    if start_at or deadline:
        schedule_note = f"\nСрок выполнения: с {start_at or 'сейчас'} до {deadline or 'конца дня'}.\n"
    timed_brief = f"{schedule_note}{brief}"

    if dept == "marketing":
        result = await execute_marketing_brief(
            timed_brief,
            task_type=f"directive_{dept}",
            force_local=True,
        )
        return {
            "department": dept,
            "department_label": label,
            "role": preset.role if preset else "CMO",
            "brief": brief,
            "summary": result.get("summary") or result.get("error", ""),
            "error": result.get("error"),
            "cost_rub": float(result.get("cost_rub", 0) or 0),
            "mode": result.get("mode", "local"),
            "raw": {k: v for k, v in result.items() if k not in ("cmo_plan",)},
        }

    if not preset:
        return {
            "department": dept,
            "department_label": label,
            "role": dept,
            "brief": brief,
            "summary": "",
            "error": f"Неизвестный отдел: {dept}",
            "cost_rub": 0.0,
        }

    if not await can_spend_office(department=dept):
        kpi = await get_kpi_snapshot()
        stats = await get_department_stats()
        fallback = (
            f"{label}: бюджет LLM исчерпан. "
            f"KPI — лиды {kpi.get('targets', 0)}, сделки {stats.get('deals', {})}. "
            "Задача не выполнена через GPTunnel."
        )
        return {
            "department": dept,
            "department_label": label,
            "role": preset.role,
            "brief": brief,
            "summary": fallback,
            "error": "Бюджет LLM исчерпан",
            "cost_rub": 0.0,
            "mode": "budget_blocked",
        }

    kpi = await get_kpi_snapshot()
    stats = await get_department_stats()
    ws = await office_db.get_workstation_by_preset(preset.id)
    if ws:
        system = build_agent_system_prompt(ws)
        role = ws.role
        tier = ws.model_tier
    else:
        system = (
            f"Ты — {preset.role} веб-студии ВебШтрих. {preset.backstory}\n"
            "Дай конкретный результат по задаче: что сделано, артефакты, следующие шаги."
        )
        role = preset.role
        tier = preset.model_tier

    context = (
        f"KPI: лиды {kpi.get('targets', 0)}, email {kpi.get('emails_sent', 0)}, "
        f"расход LLM {kpi.get('llm_cost_rub', 0):.1f} ₽.\n"
        f"Статистика отдела: {stats}\n\n"
        f"{schedule_note}"
        f"Задача от COO (часть общего поручения CEO):\n{brief}\n\n"
        "Ответь структурно:\n"
        "1. Что сделано\n2. Конкретные результаты/тексты/планы\n3. Что нужно от других отделов\n"
        "4. Блокеры"
    )
    prompt = f"{system}\n\n{context}"

    llm = OfficeLLMClient()
    try:
        resp = await llm.complete(role, prompt, tier=tier, department=dept, max_tokens=2000)
    except OfficeLLMError as exc:
        return {
            "department": dept,
            "department_label": label,
            "role": role,
            "brief": brief,
            "summary": "",
            "error": str(exc),
            "cost_rub": 0.0,
        }

    if resp.content.startswith("Бюджет LLM"):
        return {
            "department": dept,
            "department_label": label,
            "role": role,
            "brief": brief,
            "summary": resp.content,
            "error": resp.content,
            "cost_rub": 0.0,
        }

    return {
        "department": dept,
        "department_label": label,
        "role": role,
        "brief": brief,
        "summary": resp.content,
        "error": None,
        "cost_rub": resp.cost_rub,
        "mode": "local",
    }
