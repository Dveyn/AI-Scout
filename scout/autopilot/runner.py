from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from scout.agent.cost_guard import can_spend_llm
from scout.agent.runner import process_job
from scout.config import SCOUT_ROOT, get_settings
from scout.inbox.imap_checker import check_inbox_and_notify
from scout.models.schemas import JobCreate, JobReport, SendStatus, Tone
from scout.notify.telegram import send_telegram
from scout.outreach.channel_links import best_manual_channel
from scout.outreach.service import build_job_report, send_lead_outreach
from scout.presets.loader import load_preset
from scout.runtime.daily_state import llm_spent_today
from scout.storage import db

logger = logging.getLogger(__name__)

QUEUE_PATH = Path(__file__).resolve().parent / "queue.yaml"
STATE_PATH = SCOUT_ROOT / "data" / "autopilot_state.json"


def _load_queue(path: Path | None = None) -> dict[str, Any]:
    queue_file = path or QUEUE_PATH
    if not queue_file.exists():
        raise FileNotFoundError(f"Очередь не найдена: {queue_file}")
    data = yaml.safe_load(queue_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("campaigns"):
        raise ValueError(f"Некорректная очередь: {queue_file}")
    return data


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_index": -1, "runs_today": 0, "last_run_date": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_index": -1, "runs_today": 0, "last_run_date": None}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_campaign(entry: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    preset_name = entry.get("preset")
    preset: dict[str, Any] = {}
    if preset_name:
        preset = load_preset(preset_name)

    camp = {
        "preset": preset_name,
        "icp": entry.get("icp") or preset.get("icp", ""),
        "product": entry.get("product") or preset.get("product", ""),
        "offer": entry.get("offer") or preset.get("offer"),
        "query": entry.get("query") or preset.get("query", ""),
        "city": entry.get("city") or preset.get("city", ""),
        "limit": int(entry.get("limit") or defaults.get("limit") or 12),
        "tone": entry.get("tone") or preset.get("tone", "business"),
        "agent_skill": entry.get("skill") or preset.get("skill", "outreach-writer"),
        "generate_followups": entry.get(
            "generate_followups",
            defaults.get("generate_followups", True),
        ),
        "auto_send": entry.get("auto_send", defaults.get("auto_send", True)),
    }
    if not camp["query"] or not camp["city"]:
        raise ValueError(f"Кампания без query/city: {entry}")
    return camp


def _pick_campaign(queue: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], int]:
    campaigns = queue["campaigns"]
    defaults = queue.get("defaults") or {}
    next_index = (int(state.get("last_index", -1)) + 1) % len(campaigns)
    return _resolve_campaign(campaigns[next_index], defaults), next_index


def _bump_daily_counter(state: dict[str, Any]) -> dict[str, Any]:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if state.get("last_run_date") != today:
        state["runs_today"] = 0
        state["last_run_date"] = today
    state["runs_today"] = int(state.get("runs_today", 0)) + 1
    state["last_run_at"] = datetime.utcnow().isoformat()
    return state


def _format_report(label: str, report: JobReport) -> str:
    settings = get_settings()
    spent = llm_spent_today()
    budget = settings.llm_daily_budget_rub
    budget_line = f"LLM сегодня: {spent:.2f}₽"
    if budget > 0:
        budget_line += f" / {budget:.0f}₽"
    return (
        f"{label}\n"
        f"Собрано: {report.collected} | Target: {report.targets}\n"
        f"Отправлено: {report.sent} | Ручные: {report.ready_manual}\n"
        f"Нет email: {report.no_contact} | Дубли: {report.duplicate}\n"
        f"{budget_line}"
    )


async def digest_ready_leads() -> int:
    """Telegram-дайджест лидов для ручной отправки в мессенджеры."""
    leads = await db.list_ready_leads(limit=15)
    if not leads:
        return 0

    lines = ["📱 Ручная отправка (мессенджеры):", ""]
    for lead in leads[:10]:
        ch = best_manual_channel(lead.outreach_channels)
        url = ch.url if ch else (lead.fallback_text or "—")
        lines.append(f"• {lead.raw.name}")
        lines.append(f"  {url}")
    if len(leads) > 10:
        lines.append(f"…ещё {len(leads) - 10} в дашборде")

    await send_telegram("\n".join(lines))
    return len(leads)


async def run_autopilot_campaign(*, queue_path: Path | None = None, force: bool = False) -> JobReport | None:
    settings = get_settings()
    if not settings.autopilot_enabled and not force:
        logger.info("Autopilot disabled (AUTOPILOT_ENABLED=false)")
        return None

    if not can_spend_llm(estimated_rub=2.0):
        await send_telegram("⏸ Autopilot: дневной бюджет LLM исчерпан")
        return None

    state = _load_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if state.get("last_run_date") != today:
        state["runs_today"] = 0
        state["last_run_date"] = today

    if not force and int(state.get("runs_today", 0)) >= settings.autopilot_max_runs_per_day:
        logger.info("Daily autopilot limit reached (%d)", settings.autopilot_max_runs_per_day)
        return None

    queue = _load_queue(queue_path)
    camp, index = _pick_campaign(queue, state)
    auto_send = bool(camp["auto_send"]) or settings.auto_send_email

    job = await db.create_job(
        JobCreate(
            icp=camp["icp"],
            product=camp["product"],
            offer=camp["offer"],
            query=camp["query"],
            city=camp["city"],
            limit=camp["limit"],
            tone=Tone(camp["tone"]),
            auto_send=auto_send,
            agent_skill=camp.get("agent_skill"),
            preset=camp.get("preset"),
            generate_followups=bool(camp.get("generate_followups", True)),
        )
    )

    logger.info("Autopilot job %s: %s / %s", job.id, camp["query"], camp["city"])
    await process_job(job.id)
    job = await db.get_job(job.id)
    if job and job.status.value == "failed":
        await send_telegram(f"❌ Autopilot ошибка\n{job.error}")
        raise RuntimeError(job.error or "Autopilot job failed")

    report = await build_job_report(job.id)
    state["last_index"] = index
    state = _bump_daily_counter(state)
    _save_state(state)

    await send_telegram(_format_report(f"✅ {camp['query']} · {camp['city']}", report))
    await digest_ready_leads()
    return report


def _followup_due_touch(lead, *, delay_days: int, delay_days_touch3: int) -> int | None:
    now = datetime.utcnow()
    threshold = timedelta(days=delay_days)
    threshold3 = timedelta(days=delay_days_touch3)

    if lead.sequence_touch_sent == 1:
        fu2 = next((f for f in lead.followups if f.touch == 2), None)
        if not fu2 or fu2.send_status == SendStatus.SENT:
            return None
        if lead.sent_at and now - lead.sent_at.replace(tzinfo=None) >= threshold:
            return 2
        return None

    if lead.sequence_touch_sent == 2:
        fu2 = next((f for f in lead.followups if f.touch == 2), None)
        fu3 = next((f for f in lead.followups if f.touch == 3), None)
        if not fu3 or fu3.send_status == SendStatus.SENT:
            return None
        sent_at = fu2.sent_at if fu2 and fu2.sent_at else lead.sent_at
        if sent_at and now - sent_at.replace(tzinfo=None) >= threshold3:
            return 3
    return None


async def run_due_followups(*, dry_run: bool = False) -> dict[str, int]:
    settings = get_settings()
    leads = await db.list_leads_for_followup()
    stats = {"checked": len(leads), "sent": 0, "skipped": 0, "failed": 0}

    for lead in leads:
        touch = _followup_due_touch(
            lead,
            delay_days=settings.followup_delay_days,
            delay_days_touch3=settings.followup_delay_days_touch3,
        )
        if not touch:
            stats["skipped"] += 1
            continue
        if dry_run:
            stats["sent"] += 1
            continue

        updated = await send_lead_outreach(lead.id, touch=touch)
        fu = next((f for f in updated.followups if f.touch == touch), None)
        if fu and fu.send_status == SendStatus.SENT:
            stats["sent"] += 1
        else:
            stats["skipped"] += 1

    if stats["sent"] and not dry_run:
        await send_telegram(
            f"📬 Follow-up: {stats['sent']} отправлено, {stats['skipped']} пропущено"
        )
    return stats


async def run_daily(*, queue_path: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Полный дневной цикл: IMAP → follow-up → кампания."""
    inbox = await check_inbox_and_notify()
    followup_stats = await run_due_followups()
    report = await run_autopilot_campaign(queue_path=queue_path, force=force)
    return {"inbox_replies": len(inbox), "followups": followup_stats, "campaign": report}
