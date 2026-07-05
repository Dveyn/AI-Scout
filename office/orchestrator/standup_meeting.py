from __future__ import annotations

import json
import logging
import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from office.bridge.department_tasks import create_department_task
from office.bridge.scout_stats import get_kpi_snapshot
from office.bridge.telegram_digest import send_standup_digest
from office.crews.loader import department_heads, head_preset_for_department
from office.llm import OfficeLLMClient, OfficeLLMError, can_spend_office, llm_available
from office.models import (
    MeetingItemRecord,
    MeetingRecord,
    MeetingStatus,
    ModelTier,
    StandupResult,
)
from office.storage import db as office_db

logger = logging.getLogger(__name__)

STANDUP_TEMPLATE = """Standup-отчёт по шаблону (кратко, до 120 слов):
1. Что сделано вчера
2. План на сегодня
3. Блокеры

KPI (без выдумок, только из данных):
{kpi}

Отдел: {department}
Роль: {role}
"""


class StandupState(TypedDict):
    meeting: dict[str, Any]
    kpi: dict[str, Any]
    items: Annotated[list[dict[str, Any]], operator.add]
    coo_synthesis: str
    day_plan: Annotated[list[str], operator.add]
    cost_rub: float


async def _init_meeting(state: StandupState) -> StandupState:
    kpi = await get_kpi_snapshot()
    meeting = MeetingRecord.model_validate(state["meeting"])
    meeting.kpi_snapshot = kpi
    meeting.status = MeetingStatus.IN_PROGRESS
    meeting.agenda = meeting.agenda or "Ежедневный standup: отчёты руководителей отделов"
    saved = await office_db.save_meeting(meeting)
    return {**state, "meeting": saved.model_dump(mode="json"), "kpi": kpi}


async def _collect_head_reports(state: StandupState) -> StandupState:
    meeting = MeetingRecord.model_validate(state["meeting"])
    kpi = state.get("kpi", {})
    llm = OfficeLLMClient()
    items: list[dict[str, Any]] = []
    total_cost = state.get("cost_rub", 0.0)

    for dept_slug, head_preset_id in department_heads().items():
        if dept_slug == "executive":
            continue
        preset = head_preset_for_department(dept_slug)
        if not preset:
            continue
        if not await can_spend_office(department=dept_slug):
            break
        prompt = STANDUP_TEMPLATE.format(
            kpi=json.dumps(kpi, ensure_ascii=False)[:800],
            department=dept_slug,
            role=preset.role,
        )
        resp = await llm.complete(
            preset.role,
            prompt,
            tier=ModelTier.STRATEGY,
            department=dept_slug,
            max_tokens=400,
        )
        if resp.content.startswith("Бюджет LLM"):
            raise OfficeLLMError(resp.content)
        total_cost += resp.cost_rub
        report_text = resp.content[:600]
        item = MeetingItemRecord(
            meeting_id=meeting.id,
            department_slug=dept_slug,
            head_role=preset.role,
            report=report_text,
            plan="",
            blockers="",
        )
        saved = await office_db.save_meeting_item(item)
        items.append(saved.model_dump(mode="json"))

    return {**state, "items": items, "cost_rub": total_cost}


async def _coo_synthesize(state: StandupState) -> StandupState:
    if not await can_spend_office(department="executive"):
        return state
    items = state.get("items", [])
    llm = OfficeLLMClient()
    reports = "\n\n".join(
        f"### {i.get('head_role')} ({i.get('department_slug')})\n{i.get('report', '')}"
        for i in items
    )
    prompt = f"""Ты COO веб-студии. Синтезируй standup-отчёты руководителей.

{reports}

Верни JSON:
{{
  "synthesis": "2-3 предложения итога",
  "day_plan": ["задача 1", "задача 2", "задача 3"]
}}"""
    resp = await llm.complete("COO", prompt, tier=ModelTier.STRATEGY, department="executive")
    synthesis = resp.content
    day_plan: list[str] = []
    try:
        start = resp.content.find("{")
        end = resp.content.rfind("}") + 1
        if start >= 0:
            parsed = json.loads(resp.content[start:end])
            synthesis = parsed.get("synthesis", synthesis)
            day_plan = list(parsed.get("day_plan", []))[:6]
    except json.JSONDecodeError:
        day_plan = [synthesis[:120]] if synthesis else []

    return {
        **state,
        "coo_synthesis": synthesis,
        "day_plan": day_plan,
        "cost_rub": state.get("cost_rub", 0.0) + resp.cost_rub,
    }


async def _create_day_tasks(state: StandupState) -> StandupState:
    meeting = MeetingRecord.model_validate(state["meeting"])
    for i, plan_item in enumerate(state.get("day_plan", [])[:5]):
        await create_department_task(
            agent_key="cmo" if i % 2 == 0 else "smm",
            task_type="standup_day_plan",
            brief=plan_item,
            priority=8,
            requires_approval=True,
            input_json={"meeting_id": meeting.id},
        )
    meeting.status = MeetingStatus.COMPLETED
    meeting.completed_at = datetime.utcnow()
    meeting.transcript_summary = state.get("coo_synthesis", "")
    meeting.decisions = state.get("day_plan", [])
    await office_db.save_meeting(meeting)
    digest = "📋 Standup AI Office\n\n" + (meeting.transcript_summary or "")
    if meeting.decisions:
        digest += "\n\nПлан дня:\n" + "\n".join(f"• {d}" for d in meeting.decisions[:5])
    await send_standup_digest(digest)
    return {**state, "meeting": meeting.model_dump(mode="json")}


def build_standup_graph():
    graph = StateGraph(StandupState)
    graph.add_node("init", _init_meeting)
    graph.add_node("reports", _collect_head_reports)
    graph.add_node("synthesize", _coo_synthesize)
    graph.add_node("tasks", _create_day_tasks)
    graph.set_entry_point("init")
    graph.add_edge("init", "reports")
    graph.add_edge("reports", "synthesize")
    graph.add_edge("synthesize", "tasks")
    graph.add_edge("tasks", END)
    return graph.compile()


async def run_standup_llm(*, agenda: str = "") -> StandupResult:
    meeting = MeetingRecord(agenda=agenda or "Ежедневный standup CEO")
    meeting.participants = list(department_heads().values())
    await office_db.save_meeting(meeting)

    app = build_standup_graph()
    initial: StandupState = {
        "meeting": meeting.model_dump(mode="json"),
        "kpi": {},
        "items": [],
        "coo_synthesis": "",
        "day_plan": [],
        "cost_rub": 0.0,
    }
    final = await app.ainvoke(initial)
    m = MeetingRecord.model_validate(final["meeting"])
    items = [MeetingItemRecord.model_validate(i) for i in final.get("items", [])]
    return StandupResult(
        meeting=m,
        items=items,
        coo_synthesis=final.get("coo_synthesis", ""),
        day_plan=final.get("day_plan", []),
        cost_rub=final.get("cost_rub", 0.0),
    )


_DEPT_LABELS = {
    "marketing": "Маркетинг",
    "sales": "Продажи",
    "leadgen": "Лидоген",
    "production": "Продакшн",
}


def _local_head_report(dept_slug: str, role: str, kpi: dict, dept_stats: dict) -> str:
    deals = dept_stats.get("deals", {}) if dept_stats else {}
    in_progress = deals.get("new", 0) + deals.get("in_progress", 0)
    return (
        f"{_DEPT_LABELS.get(dept_slug, dept_slug)} ({role}): "
        f"лиды {kpi.get('targets', 0)}, email {kpi.get('emails_sent', 0)}, "
        f"сделки в работе {in_progress}. "
        "План — задачи из /department. Отчёт без LLM (KPI локально)."
    )


def _local_day_plan(kpi: dict, dept_stats: dict) -> list[str]:
    deals = dept_stats.get("deals", {}) if dept_stats else {}
    plan = []
    if kpi.get("targets", 0) < 5:
        plan.append("Запустить Scout — набрать целевые лиды")
    plan.append("Утвердить задачи CMO в /department/cmo")
    if deals.get("new", 0) > 0:
        plan.append(f"Обработать {deals['new']} новых сделок")
    plan.append("Проверить контент и рекламу на публикацию")
    return plan[:5]


async def run_standup_local(*, agenda: str = "") -> StandupResult:
    from office.bridge.scout_stats import get_department_stats

    kpi = await get_kpi_snapshot()
    dept_stats = await get_department_stats()
    meeting = MeetingRecord(
        agenda=agenda or "Standup (локально, без GPTunnel)",
        status=MeetingStatus.IN_PROGRESS,
        kpi_snapshot=kpi,
    )
    meeting.participants = list(department_heads().values())
    await office_db.save_meeting(meeting)

    items: list[MeetingItemRecord] = []
    for dept_slug in ("marketing", "sales", "leadgen", "production"):
        preset = head_preset_for_department(dept_slug)
        if not preset:
            continue
        item = MeetingItemRecord(
            meeting_id=meeting.id,
            department_slug=dept_slug,
            head_role=preset.role,
            report=_local_head_report(dept_slug, preset.role, kpi, dept_stats),
            plan="См. план дня",
        )
        items.append(await office_db.save_meeting_item(item))

    day_plan = _local_day_plan(kpi, dept_stats)
    synthesis = (
        f"Локальный standup. Лиды: {kpi.get('targets', 0)}, "
        f"GPTunnel сегодня: {kpi.get('llm_cost_rub', 0):.1f} ₽."
    )

    for i, plan_item in enumerate(day_plan):
        await create_department_task(
            agent_key="cmo" if i % 2 == 0 else "smm",
            task_type="standup_day_plan",
            brief=plan_item,
            priority=8,
            requires_approval=True,
            input_json={"meeting_id": meeting.id, "source": "local_standup"},
        )

    meeting.status = MeetingStatus.COMPLETED
    meeting.completed_at = datetime.utcnow()
    meeting.transcript_summary = synthesis
    meeting.decisions = day_plan
    await office_db.save_meeting(meeting)
    digest = "📋 Standup (локально)\n\n" + synthesis
    await send_standup_digest(digest)

    return StandupResult(
        meeting=meeting,
        items=items,
        coo_synthesis=synthesis,
        day_plan=day_plan,
        cost_rub=0.0,
    )


async def run_standup(*, agenda: str = "") -> StandupResult:
    if not llm_available() or not await can_spend_office():
        return await run_standup_local(agenda=agenda)
    try:
        return await run_standup_llm(agenda=agenda)
    except (OfficeLLMError, Exception) as exc:
        logger.warning("standup LLM failed, fallback local: %s", exc)
        result = await run_standup_local(agenda=agenda)
        result.meeting.transcript_summary += f"\n\n⚠️ GPTunnel недоступен: {exc}"
        return result
