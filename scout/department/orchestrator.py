from __future__ import annotations

import logging
from datetime import datetime

from scout.agent.cost_guard import can_spend_llm
from scout.autopilot.runner import run_daily as run_autopilot_daily
from scout.config import get_settings
from scout.department.agents.ads import AdsAgent
from scout.department.agents.analytics import AnalyticsAgent
from scout.department.agents.cmo import CMOAgent
from scout.department.agents.seo import SEOAgent
from scout.department.agents.smm import SMMAgent
from scout.department.integrations import cursor_bridge
from scout.department.kpi import build_report_without_llm, format_telegram_digest
from scout.department.local_state import mark_cmo_cycle_done, should_run_cmo_cycle
from scout.department.models import (
    AdCreativeStatus,
    ContentStatus,
    DepartmentAgent,
    TaskStatus,
)
from scout.inbox.imap_checker import check_inbox_and_notify
from scout.notify.telegram import send_telegram
from scout.storage import db as scout_db
from scout.storage import department_db as db

logger = logging.getLogger(__name__)


async def _handle_inbox_replies(*, use_cursor: bool) -> list[dict]:
    matched = await check_inbox_and_notify()
    for reply in matched:
        if use_cursor:
            path = cursor_bridge.export_inbox_handoff(reply)
            await cursor_bridge.trigger_cursor_webhook(
                "sales_reply",
                {"type": "sales_reply", "file": path.name, "deal_id": reply.get("lead_id")},
            )
            continue
        if not can_spend_llm():
            break
        from scout.department.agents.sales import SalesAgent

        sales = SalesAgent()
        draft = await sales.handle_inbox_reply(reply)
        if reply.get("lead_id"):
            path = cursor_bridge.export_sales_reply_handoff(
                reply.get("lead_id", "unknown"), reply, draft
            )
            await cursor_bridge.trigger_cursor_webhook(
                "sales_reply",
                {"type": "sales_reply", "file": path.name, "deal_id": reply.get("lead_id")},
            )
    return matched


async def _publish_approved_content() -> dict[str, int]:
    """Publish content already in DB (from Cursor verdicts) — no LLM."""
    stats = {"smm": 0, "seo": 0, "published": 0}
    smm = SMMAgent()
    seo = SEOAgent()
    posts = await db.list_content_posts(limit=50)
    for post in posts:
        if post.status != ContentStatus.SCHEDULED:
            continue
        try:
            if post.platform.lower() in ("vk", "telegram", "tenchat"):
                if await smm.publish_post(post):
                    stats["published"] += 1
                stats["smm"] += 1
            elif post.platform.lower() == "seo":
                if await seo.publish_post(post):
                    stats["published"] += 1
                stats["seo"] += 1
        except Exception as exc:
            logger.warning("Publish %s failed: %s", post.id, exc)
    return stats


async def _execute_tasks_local() -> dict[str, int]:
    """Run SMM/SEO/Ads agents via GPTunnel."""
    stats = {"smm": 0, "seo": 0, "ads": 0, "published": 0}
    smm = SMMAgent()
    seo = SEOAgent()
    ads = AdsAgent()

    tasks = await db.list_tasks(limit=50)
    for task in tasks:
        if task.status != TaskStatus.APPROVED:
            continue
        if not can_spend_llm():
            logger.warning("LLM budget exceeded, stopping task execution")
            break
        try:
            if task.agent == DepartmentAgent.SMM:
                posts = await smm.execute_task(task)
                stats["smm"] += 1
                for post in posts:
                    if await smm.publish_post(post):
                        stats["published"] += 1
            elif task.agent == DepartmentAgent.SEO:
                posts = await seo.execute_task(task)
                stats["seo"] += 1
                for post in posts:
                    if await seo.publish_post(post):
                        stats["published"] += 1
            elif task.agent == DepartmentAgent.ADS:
                await ads.execute_task(task)
                stats["ads"] += 1
        except Exception as exc:
            logger.exception("Task %s failed: %s", task.id, exc)
            task.status = TaskStatus.FAILED
            await db.update_task(task)
    return stats


async def _run_cursor_department_cycle(report, deals) -> int:
    """Export handoff + webhook — CMO/SMM/SEO/Analytics run in Cursor."""
    path = cursor_bridge.export_department_cycle_handoff(report, deals)
    triggered = await cursor_bridge.trigger_cursor_webhook(
        "department_daily",
        {"type": "department_daily", "file": path.name, "report_date": report.report_date},
    )
    if not triggered:
        logger.info(
            "Cursor webhook not configured — handoff at %s (open in Cursor manually)",
            path,
        )
    pending_ads = await db.list_ad_creatives(status=AdCreativeStatus.PENDING_APPROVAL)
    extra = cursor_bridge.export_pending_approval(pending_ads, [])
    return 1 + len(extra)


async def run_daily(*, force: bool = False) -> dict:
    settings = get_settings()
    use_cursor = settings.department_uses_cursor_llm()

    if not settings.department_enabled:
        logger.info("Department disabled, running autopilot only")
        return await run_autopilot_daily(force=force)

    result: dict = {
        "mode": "cursor" if use_cursor else "local",
        "inbox_replies": 0,
        "autopilot": None,
        "report": None,
        "tasks_created": 0,
        "task_stats": {},
        "cursor_handoffs": 0,
        "cursor_outputs": {},
        "verdicts_applied": 0,
    }

    await scout_db.init_db()
    result["verdicts_applied"] = await cursor_bridge.apply_verdicts_from_files()
    result["cursor_outputs"] = await cursor_bridge.apply_cursor_outputs()

    result["inbox_replies"] = len(await _handle_inbox_replies(use_cursor=use_cursor))

    # Scout outreach (Yandex Maps + письма) — единственный платный GPTunnel в cursor-режиме
    if settings.scout_outreach_llm_enabled:
        result["autopilot"] = await run_autopilot_daily(force=force)
    else:
        logger.info("scout_outreach_llm_enabled=false — кампании пропущены")
        result["autopilot"] = None

    result["task_stats"] = await _publish_approved_content()

    run_cmo = force or should_run_cmo_cycle()
    if not run_cmo:
        logger.info("Test mode: daily CMO cycle skipped (already ran today)")
        return result

    if use_cursor:
        report = await build_report_without_llm()
        result["report"] = report
        deals = await db.list_deals(limit=50)
        result["cursor_handoffs"] = await _run_cursor_department_cycle(report, deals)
        await send_telegram(format_telegram_digest(report))
        mark_cmo_cycle_done()
        return result

    if not can_spend_llm():
        logger.warning("LLM budget exceeded — department agents skipped")
        return result

    analytics = AnalyticsAgent()
    report = await analytics.generate_daily_report()
    result["report"] = report
    deals = await db.list_deals(limit=50)
    cmo = CMOAgent()
    tasks = await cmo.review_and_plan(report, deals)
    result["tasks_created"] = len(tasks)
    result["task_stats"] = await _execute_tasks_local()
    pending_ads_list = await db.list_ad_creatives(status=AdCreativeStatus.PENDING_APPROVAL)
    pending_cmo = [t for t in tasks if t.status == TaskStatus.PENDING_CMO_APPROVAL]
    cursor_bridge.export_daily_handoff(report, tasks, deals)
    handoff_paths = cursor_bridge.export_pending_approval(pending_ads_list, pending_cmo)
    result["cursor_handoffs"] = len(handoff_paths)
    for creative in pending_ads_list:
        await cursor_bridge.trigger_cursor_webhook(
            "ads_approval", {"type": "ads_approval", "creative_id": creative.id}
        )
    if pending_cmo:
        await cursor_bridge.trigger_cursor_webhook(
            "cmo_review", {"type": "cmo_review", "tasks_count": len(pending_cmo)}
        )
    await send_telegram(analytics.format_telegram_digest(report))
    mark_cmo_cycle_done()
    return result
