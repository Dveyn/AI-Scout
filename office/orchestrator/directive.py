from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from office.api.events import publish_event
from office.bridge.scout_stats import get_kpi_snapshot
from office.crews.department_runner import DEPT_LABELS, execute_department_brief
from office.llm import OfficeLLMClient, OfficeLLMError, can_spend_office
from office.models import AgentStatus, DirectiveRecord, DirectiveStatus, ModelTier
from office.storage import db as office_db

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """Ты — COO веб-студии ВебШтрих. CEO дал ОДНУ задачу — ты распределяешь её по отделам с расписанием.

Задача CEO:
{brief}

KPI:
{kpi}

Сейчас: {now}

Верни ТОЛЬКО JSON:
{{
  "coo_plan": "как координируешь работу (2-4 предложения)",
  "tasks": [
    {{
      "department": "marketing|sales|leadgen|production",
      "brief": "конкретное поручение отделу — что именно сделать",
      "start_at": "ДД.ММ ЧЧ:ММ",
      "deadline": "ДД.ММ ЧЧ:ММ",
      "order": 1
    }}
  ]
}}

Правила:
- 2-4 отдела, только нужные
- start_at/deadline — реалистичные слоты в ближайшие 1-3 дня
- order — порядок запуска (1 = первый)
- brief = исполнимый результат, не общие слова
"""


REPORT_PROMPT = """Ты — COO. CEO поставил задачу и ждёт ГОТОВЫЙ РЕЗУЛЬТАТ — не внутренний отчёт, а то, что можно сразу использовать.

Задача CEO:
{brief}

План и расписание:
{coo_plan}

{schedule_block}

Работа отделов:
{dept_block}

Собери для CEO на русском:

# Готовый результат
(главный deliverable — тексты, планы, списки, КП, что просил CEO; можно копировать и использовать)

# Что сделали отделы
(кратко по каждому: что сделано, к какому сроку)

# Если нужно от CEO
(только если без CEO не двинуться дальше; иначе «ничего»)

Не выдумывай. Бери только из результатов отделов.
"""


class DirectiveState(TypedDict):
    directive_id: str
    brief: str
    coo_plan: str
    tasks: list[dict[str, Any]]
    dept_results: list[dict[str, Any]]
    final_report: str
    cost_rub: float
    error: str


def _parse_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return {}


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%d.%m %H:%M")


def _default_tasks(brief: str) -> list[dict[str, Any]]:
    base = datetime.utcnow()
    slots = [
        ("marketing", f"Маркетинг: план и материалы — {brief}", 0, 4),
        ("leadgen", f"Лидоген: список целевых лидов и подход — {brief}", 2, 6),
        ("sales", f"Продажи: скрипт и черновик КП — {brief}", 4, 8),
    ]
    tasks: list[dict[str, Any]] = []
    for order, (dept, task_brief, start_h, end_h) in enumerate(slots, 1):
        start = base + timedelta(hours=start_h)
        end = base + timedelta(hours=end_h)
        tasks.append(
            {
                "department": dept,
                "brief": task_brief,
                "start_at": _fmt_dt(start),
                "deadline": _fmt_dt(end),
                "order": order,
            }
        )
    return tasks


def _normalize_tasks(raw: list[Any], brief: str) -> list[dict[str, Any]]:
    base = datetime.utcnow()
    normalized: list[dict[str, Any]] = []
    for i, item in enumerate(raw[:4]):
        if not isinstance(item, dict):
            continue
        dept = str(item.get("department", "marketing")).lower()
        if dept not in DEPT_LABELS:
            continue
        start = base + timedelta(hours=int(item.get("order", i + 1)) - 1)
        end = start + timedelta(hours=3)
        normalized.append(
            {
                "department": dept,
                "brief": str(item.get("brief", brief))[:2000],
                "start_at": str(item.get("start_at") or _fmt_dt(start)),
                "deadline": str(item.get("deadline") or _fmt_dt(end)),
                "order": int(item.get("order", i + 1)),
            }
        )
    if not normalized:
        normalized = _default_tasks(brief)
    return sorted(normalized, key=lambda t: t.get("order", 99))


def _schedule_block(tasks: list[dict[str, Any]]) -> str:
    lines = []
    for t in tasks:
        lines.append(
            f"- [{t.get('order')}] {DEPT_LABELS.get(t['department'], t['department'])}: "
            f"{t.get('start_at')} → {t.get('deadline')} — {t.get('brief', '')[:120]}"
        )
    return "\n".join(lines) or "—"


async def _decompose(state: DirectiveState) -> DirectiveState:
    brief = state["brief"]
    directive_id = state["directive_id"]
    await office_db.update_directive(directive_id, status=DirectiveStatus.PLANNING)
    publish_event("directive_planning", {"directive_id": directive_id})

    if not await can_spend_office(department="executive"):
        plan = "COO распределил задачи по отделам (расписание ниже)."
        tasks = _default_tasks(brief)
        await office_db.update_directive(directive_id, coo_plan=plan, schedule=tasks)
        return {**state, "coo_plan": plan, "tasks": tasks, "cost_rub": 0.0}

    kpi = await get_kpi_snapshot()
    llm = OfficeLLMClient()
    now = _fmt_dt(datetime.utcnow())
    try:
        resp = await llm.complete(
            "COO",
            DECOMPOSE_PROMPT.format(
                brief=brief,
                kpi=json.dumps(kpi, ensure_ascii=False),
                now=now,
            ),
            tier=ModelTier.STRATEGY,
            department="executive",
            max_tokens=1500,
        )
    except OfficeLLMError as exc:
        plan = f"План по умолчанию ({exc})"
        tasks = _default_tasks(brief)
        await office_db.update_directive(directive_id, coo_plan=plan, schedule=tasks)
        return {**state, "coo_plan": plan, "tasks": tasks, "error": str(exc)}

    parsed = _parse_json_object(resp.content)
    plan = parsed.get("coo_plan") or resp.content[:800]
    tasks = _normalize_tasks(parsed.get("tasks") or [], brief)

    await office_db.update_directive(directive_id, coo_plan=plan, schedule=tasks)
    publish_event("directive_scheduled", {"directive_id": directive_id, "tasks": len(tasks)})

    return {
        **state,
        "coo_plan": plan,
        "tasks": tasks,
        "cost_rub": state.get("cost_rub", 0.0) + resp.cost_rub,
    }


async def _execute_departments(state: DirectiveState) -> DirectiveState:
    directive_id = state["directive_id"]
    tasks = sorted(state.get("tasks", []), key=lambda t: t.get("order", 99))
    await office_db.update_directive(directive_id, status=DirectiveStatus.EXECUTING)
    publish_event("directive_executing", {"directive_id": directive_id})

    coo_ws = await office_db.get_workstation_by_preset("coo")
    if coo_ws:
        await office_db.update_workstation_status(
            coo_ws.id, AgentStatus.WORKING, current_task=state["brief"][:200]
        )
        await office_db.log_activity(coo_ws.id, "run", "COO: расписание согласовано, отделы берут в работу")

    results: list[dict[str, Any]] = []
    total_cost = state.get("cost_rub", 0.0)

    for task in tasks:
        dept = task["department"]
        schedule_line = f"с {task.get('start_at', '?')} до {task.get('deadline', '?')}"

        if coo_ws:
            await office_db.log_activity(
                coo_ws.id,
                "assign",
                f"{DEPT_LABELS.get(dept, dept)} {schedule_line}: {task['brief'][:100]}",
            )

        dept_ws = await office_db.get_workstation_by_department_head(dept)
        if dept_ws:
            await office_db.update_workstation_status(
                dept_ws.id, AgentStatus.WORKING, current_task=task["brief"][:200]
            )
            await office_db.log_activity(
                dept_ws.id,
                "start",
                f"В работе {schedule_line}",
            )

        started = datetime.utcnow()
        result = await execute_department_brief(
            dept,
            task["brief"],
            start_at=task.get("start_at", ""),
            deadline=task.get("deadline", ""),
        )
        finished = datetime.utcnow()
        result["order"] = task.get("order")
        result["start_at"] = task.get("start_at")
        result["deadline"] = task.get("deadline")
        result["started_at"] = started.isoformat()
        result["finished_at"] = finished.isoformat()
        results.append(result)
        total_cost += float(result.get("cost_rub", 0) or 0)

        if dept_ws:
            summary = (result.get("summary") or result.get("error") or "")[:1500]
            ws = await office_db.get_workstation(dept_ws.id)
            if ws:
                ws.status = AgentStatus.DONE if not result.get("error") else AgentStatus.BLOCKED
                ws.last_result = summary
                ws.current_task = task["brief"][:200]
                await office_db.save_workstation(ws)
            await office_db.log_activity(
                dept_ws.id,
                "done" if not result.get("error") else "error",
                f"Сдано {finished.strftime('%H:%M')}: {summary[:400]}",
            )

        publish_event(
            "directive_dept_done",
            {"directive_id": directive_id, "department": dept},
        )

    if coo_ws:
        await office_db.log_activity(coo_ws.id, "run", "COO: собираю готовый результат для CEO")

    return {**state, "dept_results": results, "cost_rub": total_cost}


async def _synthesize_report(state: DirectiveState) -> DirectiveState:
    brief = state["brief"]
    directive_id = state["directive_id"]
    dept_results = state.get("dept_results", [])
    tasks = state.get("tasks", [])

    dept_block_parts = []
    for r in dept_results:
        dept_block_parts.append(
            f"### {r.get('department_label', r.get('department'))}\n"
            f"Срок: {r.get('start_at', '?')} — {r.get('deadline', '?')}\n"
            f"Задача: {r.get('brief', '')}\n"
            f"Сделано ({r.get('finished_at', '')[:16]}):\n"
            f"{r.get('summary') or r.get('error') or 'нет ответа'}\n"
        )
    dept_block = "\n".join(dept_block_parts) or "Отделы не ответили."

    cost = state.get("cost_rub", 0.0)
    schedule_block = _schedule_block(tasks)

    if not await can_spend_office(department="executive"):
        report = _local_deliverable(brief, state.get("coo_plan", ""), schedule_block, dept_results)
    else:
        llm = OfficeLLMClient()
        try:
            resp = await llm.complete(
                "COO",
                REPORT_PROMPT.format(
                    brief=brief,
                    coo_plan=state.get("coo_plan", ""),
                    schedule_block=schedule_block,
                    dept_block=dept_block,
                ),
                tier=ModelTier.STRATEGY,
                department="executive",
                max_tokens=3000,
            )
            report = resp.content
            cost += resp.cost_rub
        except OfficeLLMError as exc:
            report = _local_deliverable(brief, state.get("coo_plan", ""), schedule_block, dept_results)
            report += f"\n\n⚠️ {exc}"

    await office_db.update_directive(
        directive_id,
        status=DirectiveStatus.COMPLETED,
        schedule=tasks,
        dept_results=dept_results,
        final_report=report,
        cost_rub=cost,
        completed_at=datetime.utcnow(),
    )
    publish_event("directive_completed", {"directive_id": directive_id})

    coo_ws = await office_db.get_workstation_by_preset("coo")
    if coo_ws:
        await office_db.log_activity(coo_ws.id, "done", "Готовый результат передан CEO")
        ws = await office_db.get_workstation(coo_ws.id)
        if ws:
            ws.status = AgentStatus.DONE
            ws.last_result = report[:1500]
            await office_db.save_workstation(ws)

    return {**state, "final_report": report, "cost_rub": cost}


def _local_deliverable(
    brief: str,
    plan: str,
    schedule: str,
    results: list[dict[str, Any]],
) -> str:
    lines = [
        "# Готовый результат",
        "",
        f"**Задача CEO:** {brief}",
        "",
        "## Расписание",
        schedule,
        "",
        "## План COO",
        plan or "—",
        "",
        "## Что сделали отделы",
    ]
    for r in results:
        lines.append(f"### {r.get('department_label', r.get('department'))} ({r.get('start_at')} — {r.get('deadline')})")
        lines.append(r.get("summary") or r.get("error") or "нет результата")
        lines.append("")
    lines.append("## Если нужно от CEO")
    lines.append("ничего")
    return "\n".join(lines)


def build_directive_graph():
    graph = StateGraph(DirectiveState)
    graph.add_node("decompose", _decompose)
    graph.add_node("execute", _execute_departments)
    graph.add_node("report", _synthesize_report)
    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "execute")
    graph.add_edge("execute", "report")
    graph.add_edge("report", END)
    return graph.compile()


async def run_directive(brief: str) -> DirectiveRecord:
    """CEO → COO plans schedule → departments work → deliverable for CEO."""
    directive = DirectiveRecord(brief=brief, status=DirectiveStatus.PLANNING)
    await office_db.save_directive(directive)

    app = build_directive_graph()
    initial: DirectiveState = {
        "directive_id": directive.id,
        "brief": brief,
        "coo_plan": "",
        "tasks": [],
        "dept_results": [],
        "final_report": "",
        "cost_rub": 0.0,
        "error": "",
    }
    try:
        await app.ainvoke(initial)
    except Exception as exc:
        logger.exception("directive failed")
        await office_db.update_directive(
            directive.id,
            status=DirectiveStatus.FAILED,
            final_report=f"Сбой: {exc}",
        )

    updated = await office_db.get_directive(directive.id)
    return updated or directive
