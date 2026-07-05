from __future__ import annotations

import logging
from typing import Any

from office.llm import OfficeLLMClient, OfficeLLMError, can_spend_office
from office.models import AgentStatus, ModelTier, OnlineEventRecord
from office.registry.prompts import build_agent_system_prompt
from office.storage import db as office_db
from office.tools.event_scout import (
    build_events_extraction_prompt,
    parse_events_json,
    search_online_events,
)

logger = logging.getLogger(__name__)

SCAN_BRIEF_MARKERS = (
    "мероприят",
    "вебинар",
    "мастер",
    "конференц",
    "собери",
    "найди",
    "монитор",
    "event",
    "webinar",
)


async def _set_ws(
    ws_id: str,
    *,
    status: AgentStatus,
    current_task: str = "",
    last_result: str = "",
) -> None:
    ws = await office_db.get_workstation(ws_id)
    if not ws:
        return
    ws.status = status
    ws.current_task = current_task
    if last_result:
        ws.last_result = last_result
    await office_db.save_workstation(ws)


def _is_event_scan_brief(brief: str) -> bool:
    low = brief.lower()
    return any(m in low for m in SCAN_BRIEF_MARKERS)


async def scan_and_store_events(
    *,
    brief: str = "",
    workstation_id: str | None = None,
) -> dict[str, Any]:
    if workstation_id:
        await office_db.log_activity(workstation_id, "run", "Поиск онлайн-мероприятий в интернете")

    candidates = await search_online_events()
    if workstation_id:
        await office_db.log_activity(
            workstation_id,
            "search",
            f"Найдено {len(candidates)} кандидатов в поиске",
        )

    if not candidates:
        msg = (
            "Не удалось найти мероприятия через поиск. "
            "Проверьте доступ в интернет с сервера office."
        )
        return {"error": msg, "events_saved": 0, "candidates": 0}

    if not await can_spend_office(department="executive"):
        saved = await _save_candidates_without_llm(candidates[:12], source_brief=brief)
        summary = (
            f"Сохранено {saved} мероприятий из поиска (без LLM — бюджет исчерпан). "
            "Откройте вкладку «Мероприятия»."
        )
        return {
            "mode": "search_only",
            "summary": summary,
            "events_saved": saved,
            "candidates": len(candidates),
            "cost_rub": 0.0,
        }

    if workstation_id:
        await office_db.log_activity(workstation_id, "llm", "Анализ и отбор мероприятий (GPTunnel)")

    llm = OfficeLLMClient()
    prompt = build_events_extraction_prompt(candidates, brief)
    try:
        resp = await llm.complete(
            "Секретарь CEO",
            prompt,
            tier=ModelTier.EXECUTION,
            department="executive",
            max_tokens=2500,
        )
    except OfficeLLMError as exc:
        saved = await _save_candidates_without_llm(candidates[:12], source_brief=brief)
        return {
            "error": str(exc),
            "summary": f"GPTunnel недоступен. Сохранено {saved} сырых результатов поиска.",
            "events_saved": saved,
            "candidates": len(candidates),
            "cost_rub": 0.0,
        }

    if resp.content.startswith("Бюджет LLM"):
        saved = await _save_candidates_without_llm(candidates[:12], source_brief=brief)
        return {
            "error": resp.content,
            "summary": f"Бюджет исчерпан. Сохранено {saved} результатов поиска.",
            "events_saved": saved,
            "candidates": len(candidates),
            "cost_rub": 0.0,
        }

    parsed = parse_events_json(resp.content)
    saved = 0
    for item in parsed:
        rec = OnlineEventRecord(
            title=str(item.get("title", ""))[:300],
            url=str(item.get("url", ""))[:500],
            event_type=str(item.get("event_type", "other"))[:40],
            date_hint=str(item.get("date_hint", ""))[:120],
            audience=str(item.get("audience", ""))[:300],
            relevance=int(item.get("relevance", 5) or 5),
            why_relevant=str(item.get("why_relevant", ""))[:500],
            registration_hint=str(item.get("registration_hint", ""))[:300],
            source_brief=brief[:500],
        )
        if rec.title and rec.url.startswith("http"):
            await office_db.save_online_event(rec)
            saved += 1

    summary_lines = [
        f"Найдено и сохранено {saved} мероприятий (из {len(candidates)} кандидатов поиска).",
        "Смотрите вкладку «Мероприятия» в CEO-кабинете.",
    ]
    if parsed:
        top = sorted(parsed, key=lambda x: int(x.get("relevance", 0) or 0), reverse=True)[:3]
        summary_lines.append("\nТоп по релевантности:")
        for ev in top:
            summary_lines.append(
                f"• [{ev.get('relevance', '?')}/10] {ev.get('title', '')} — {ev.get('date_hint', 'дата не указана')}"
            )

    return {
        "mode": "llm",
        "summary": "\n".join(summary_lines),
        "events_saved": saved,
        "candidates": len(candidates),
        "cost_rub": resp.cost_rub,
        "events": parsed[:12],
    }


async def _save_candidates_without_llm(
    candidates: list[dict[str, str]],
    *,
    source_brief: str,
) -> int:
    saved = 0
    for c in candidates:
        rec = OnlineEventRecord(
            title=c["title"],
            url=c["url"],
            event_type="other",
            date_hint="",
            audience="",
            relevance=5,
            why_relevant=c.get("snippet", "")[:500],
            registration_hint="",
            source_brief=source_brief[:500],
        )
        await office_db.save_online_event(rec)
        saved += 1
    return saved


async def run_secretary_task(workstation_id: str, brief: str) -> dict[str, Any]:
    ws = await office_db.get_workstation(workstation_id)
    if not ws:
        return {"error": "workstation not found"}

    await office_db.log_activity(workstation_id, "start", f"Задача: {brief[:300]}")
    await _set_ws(workstation_id, status=AgentStatus.WORKING, current_task=brief[:200])

    try:
        if _is_event_scan_brief(brief):
            result = await scan_and_store_events(brief=brief, workstation_id=workstation_id)
        else:
            if not await can_spend_office(department="executive"):
                err = "Бюджет LLM исчерпан. Проверьте LLM_DAILY_BUDGET_RUB в scout/.env"
                await office_db.log_activity(workstation_id, "error", err)
                await _set_ws(workstation_id, status=AgentStatus.BLOCKED, current_task=brief[:200], last_result=err)
                return {"error": err}

            await office_db.log_activity(workstation_id, "llm", "Ответ помощника CEO")
            llm = OfficeLLMClient()
            events = await office_db.list_online_events(limit=8)
            events_ctx = "\n".join(
                f"- {e.title} ({e.date_hint or 'без даты'}) {e.url}" for e in events[:8]
            )
            prompt = (
                f"{build_agent_system_prompt(ws)}\n\n"
                f"Последние найденные мероприятия:\n{events_ctx or 'пока нет'}\n\n"
                f"Задача CEO:\n{brief}"
            )
            try:
                resp = await llm.complete(
                    ws.role,
                    prompt,
                    tier=ws.model_tier,
                    department=ws.department_slug,
                )
            except OfficeLLMError as exc:
                await office_db.log_activity(workstation_id, "error", str(exc))
                await _set_ws(
                    workstation_id,
                    status=AgentStatus.BLOCKED,
                    current_task=brief[:200],
                    last_result=str(exc),
                )
                return {"error": str(exc)}

            result = {
                "summary": resp.content,
                "cost_rub": resp.cost_rub,
                "mode": "assistant",
            }

        if result.get("error") and not result.get("summary"):
            await office_db.log_activity(workstation_id, "error", result["error"])
            await _set_ws(
                workstation_id,
                status=AgentStatus.BLOCKED,
                current_task=brief[:200],
                last_result=result["error"],
            )
        else:
            summary = result.get("summary") or result.get("error", "Готово")
            await office_db.log_activity(workstation_id, "done", summary[:500])
            await _set_ws(
                workstation_id,
                status=AgentStatus.DONE,
                current_task=brief[:200],
                last_result=summary[:1500],
            )

        return {"workstation_id": ws.id, **result}

    except Exception as exc:
        logger.exception("secretary task failed")
        msg = f"Сбой: {exc}"
        await office_db.log_activity(workstation_id, "error", msg)
        await _set_ws(
            workstation_id,
            status=AgentStatus.BLOCKED,
            current_task=brief[:200],
            last_result=msg,
        )
        return {"error": msg, "workstation_id": ws.id}
