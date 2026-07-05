from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx

from scout.config import SCOUT_ROOT, get_settings

logger = logging.getLogger(__name__)

CURSOR_DATA = SCOUT_ROOT / "data" / "cursor"
PENDING_DIR = CURSOR_DATA / "pending"
REPORTS_DIR = CURSOR_DATA / "reports"
DONE_DIR = CURSOR_DATA / "done"
VERDICTS_DIR = CURSOR_DATA / "verdicts"


def _ensure_dirs() -> None:
    for d in (PENDING_DIR, REPORTS_DIR, DONE_DIR, VERDICTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def export_daily_handoff(report, tasks, deals) -> Path:
    """Export daily report as markdown for Cursor Cloud Agents."""
    _ensure_dirs()
    date = report.report_date
    path = REPORTS_DIR / f"{date}.md"
    k = report.kpi
    lines = [
        f"# Daily Report {date}",
        "",
        f"## Summary\n{report.summary}",
        "",
        "## KPI",
        f"- Leads: {k.targets}",
        f"- Emails sent: {k.emails_sent}",
        f"- Deals new: {k.deals_new} / won: {k.deals_won}",
        f"- Conversion: {k.conversion_rate:.1%}",
        f"- CPL: {k.cpl} | CAC: {k.cac} | ROMI: {k.romi}",
        "",
        "## Recommendations",
    ]
    for rec in report.recommendations:
        lines.append(f"- {rec}")
    lines.extend(["", "## Active Deals"])
    for d in deals[:15]:
        lines.append(f"- {d.company_name} ({d.status.value})")
    lines.extend(["", "## Pending Tasks"])
    for t in tasks[:15]:
        lines.append(f"- [{t.agent.value}] {t.task_type}: {t.brief[:80]} ({t.status.value})")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_pending_approval(ad_creatives, cmo_tasks) -> list[Path]:
    _ensure_dirs()
    paths: list[Path] = []
    now = datetime.now(timezone.utc).isoformat()

    for creative in ad_creatives:
        path = PENDING_DIR / f"ads-{creative.id}.json"
        import json

        payload = {
            "type": "ads_approval",
            "agent": "ads",
            "created_at": now,
            "creative_id": creative.id,
            "brief": creative.body[:500],
            "creatives": {
                "headlines": creative.headlines,
                "body": creative.body,
                "audience": creative.audience,
                "ab_hypothesis": creative.ab_hypothesis,
            },
            "callback": {"approve_url": f"/department/ads/{creative.id}/approve"},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)

    if cmo_tasks:
        import json

        date = datetime.utcnow().strftime("%Y-%m-%d")
        path = PENDING_DIR / f"cmo-tasks-{date}.json"
        payload = {
            "type": "cmo_review",
            "agent": "cmo",
            "created_at": now,
            "tasks": [
                {
                    "id": t.id,
                    "agent": t.agent.value,
                    "task_type": t.task_type,
                    "brief": t.brief,
                    "status": t.status.value,
                }
                for t in cmo_tasks
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)

    return paths


def export_department_cycle_handoff(report, deals) -> Path:
    """Full context for Cursor department-daily automation (no local LLM)."""
    _ensure_dirs()
    import json

    date = report.report_date
    path = PENDING_DIR / f"daily-cycle-{date}.json"
    payload = {
        "type": "department_daily",
        "agent": "cmo",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_date": date,
        "kpi": report.kpi.model_dump(),
        "summary": report.summary,
        "deals": [
            {
                "id": d.id,
                "company_name": d.company_name,
                "status": d.status.value,
                "email": d.contact_email,
            }
            for d in deals[:30]
        ],
        "instructions": (
            "Use marketing skills. Write verdicts to scout/data/cursor/verdicts/: "
            "cmo-plan-{date}.json, analytics-{date}.json, content-*.json. "
            "See .cursor/automations/README.md"
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    export_daily_handoff(report, [], deals)
    return path


def export_inbox_handoff(reply: dict) -> Path:
    """Inbox reply for Cursor — no local LLM draft."""
    _ensure_dirs()
    import json

    deal_id = reply.get("lead_id") or reply.get("from", "unknown")
    path = PENDING_DIR / f"sales-reply-{deal_id}.json"
    payload = {
        "type": "sales_reply",
        "agent": "sales",
        "deal_id": deal_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inbound": reply,
        "draft": {},
        "note": "Generate reply with cold-email / sales-enablement skills",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_sales_reply_handoff(deal_id: str, reply: dict, draft: dict) -> Path:
    _ensure_dirs()
    import json

    path = PENDING_DIR / f"sales-reply-{deal_id}.json"
    payload = {
        "type": "sales_reply",
        "agent": "sales",
        "deal_id": deal_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inbound": reply,
        "draft": draft,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_office_directive_handoff(
    directive_id: str,
    brief: str,
    *,
    kpi: dict | None = None,
) -> Path:
    """CEO task for Cursor office-directive automation."""
    _ensure_dirs()
    import json

    path = PENDING_DIR / f"office-directive-{directive_id}.json"
    payload = {
        "type": "office_directive",
        "agent": "coo",
        "directive_id": directive_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brief": brief,
        "kpi": kpi or {},
        "brand_context": ".agents/product-marketing.md",
        "instructions": (
            "Ты COO веб-студии ВебШтрих. CEO дал ОДНУ задачу. "
            "1) Разбей по отделам (marketing, sales, leadgen, production) со сроками. "
            "2) Выполни работу каждого отдела (конкретные тексты, планы, списки). "
            "3) Собери готовый результат для CEO. "
            f"Запиши ответ в scout/data/cursor/verdicts/office-directive-{directive_id}.json"
        ),
        "verdict_schema": {
            "type": "office_directive",
            "directive_id": directive_id,
            "status": "completed",
            "coo_plan": "строка",
            "schedule": [
                {
                    "department": "marketing",
                    "brief": "...",
                    "start_at": "ДД.ММ ЧЧ:ММ",
                    "deadline": "ДД.ММ ЧЧ:ММ",
                    "order": 1,
                }
            ],
            "dept_results": [
                {
                    "department": "marketing",
                    "department_label": "Маркетинг",
                    "summary": "что сделано",
                }
            ],
            "final_report": "# Готовый результат\\n...",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def apply_office_directive_verdicts() -> int:
    """Load office-directive verdicts from Cursor into office.db."""
    _ensure_dirs()
    import json

    applied = 0
    for path in list(VERDICTS_DIR.glob("office-directive-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("type") != "office_directive":
            continue
        directive_id = data.get("directive_id")
        if not directive_id:
            continue
        try:
            from office.models import DirectiveStatus
            from office.storage import db as office_db

            d = await office_db.get_directive(directive_id)
            if not d:
                mark_handoff_done(path)
                continue
            await office_db.update_directive(
                directive_id,
                status=DirectiveStatus.COMPLETED,
                coo_plan=str(data.get("coo_plan", "")),
                schedule=list(data.get("schedule") or []),
                dept_results=list(data.get("dept_results") or []),
                final_report=str(data.get("final_report", "")),
                completed_at=datetime.now(timezone.utc),
            )
            applied += 1
        except Exception as exc:
            logger.warning("office verdict %s: %s", path.name, exc)
            continue
        pending = PENDING_DIR / f"office-directive-{directive_id}.json"
        if pending.exists():
            mark_handoff_done(pending)
        mark_handoff_done(path)
    return applied


async def trigger_cursor_webhook(automation_name: str, payload: dict) -> bool:
    settings = get_settings()
    url_map = {
        "ads_approval": settings.cursor_webhook_ads_approval,
        "sales_reply": settings.cursor_webhook_sales_reply,
        "cmo_review": settings.cursor_webhook_cmo_review,
        "department_daily": settings.cursor_webhook_department_daily,
        "office_directive": settings.cursor_webhook_office_directive,
    }
    url = url_map.get(automation_name, "")
    if not url:
        return False
    headers = {}
    if settings.cursor_webhook_api_key:
        headers["Authorization"] = f"Bearer {settings.cursor_webhook_api_key}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            return resp.is_success
    except Exception as exc:
        logger.warning("Cursor webhook %s failed: %s", automation_name, exc)
        return False


def mark_handoff_done(path: Path) -> None:
    _ensure_dirs()
    if path.exists():
        shutil.move(str(path), str(DONE_DIR / path.name))


async def apply_verdicts_from_files() -> int:
    """Apply verdict JSON files written by Cursor Automations."""
    _ensure_dirs()
    from scout.department.models import AdCreativeStatus, TaskStatus
    from scout.storage import department_db as db

    applied = 0
    for path in VERDICTS_DIR.glob("*.json"):
        import json

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        verdict = data.get("verdict", "").lower()
        if data.get("type") == "office_directive":
            continue
        if data.get("type") == "ads_approval":
            cid = data.get("creative_id")
            if cid and verdict == "approve":
                await db.update_ad_creative_status(cid, AdCreativeStatus.APPROVED)
                applied += 1
            elif cid and verdict == "reject":
                await db.update_ad_creative_status(cid, AdCreativeStatus.REJECTED)
                applied += 1
        elif data.get("type") == "cmo_review":
            for task_info in data.get("tasks", []):
                tid = task_info.get("id")
                v = task_info.get("verdict", verdict).lower()
                if tid and v == "approve":
                    await db.approve_task(tid)
                    applied += 1
                elif tid and v == "reject":
                    await db.reject_task(tid)
                    applied += 1

        mark_handoff_done(path)
    return applied


async def apply_cursor_outputs() -> dict[str, int]:
    """Ingest content/plans/analytics produced by Cursor into SQLite."""
    _ensure_dirs()
    from scout.department.models import (
        AdCreativeRecord,
        AdCreativeStatus,
        ContentPostRecord,
        ContentStatus,
        DailyReportRecord,
        DepartmentAgent,
        DepartmentTaskRecord,
        TaskStatus,
    )
    from scout.storage import department_db as db

    stats = {"cmo_plans": 0, "content": 0, "analytics": 0, "ads": 0}
    AGENT_MAP = {
        "sales": DepartmentAgent.SALES,
        "smm": DepartmentAgent.SMM,
        "ads": DepartmentAgent.ADS,
        "seo": DepartmentAgent.SEO,
    }

    for path in VERDICTS_DIR.glob("*.json"):
        import json

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        kind = data.get("type", "")
        if kind == "office_directive":
            continue

        if kind == "cmo_plan":
            settings = get_settings()
            for item in data.get("tasks", []):
                agent_key = str(item.get("agent", "smm")).lower()
                agent = AGENT_MAP.get(agent_key, DepartmentAgent.SMM)
                requires = agent == DepartmentAgent.ADS and not settings.cmo_auto_approve_ads
                status = TaskStatus.APPROVED
                if settings.cmo_mode == "review" or requires:
                    status = TaskStatus.PENDING_CMO_APPROVAL
                elif agent in (DepartmentAgent.SMM, DepartmentAgent.SEO):
                    status = (
                        TaskStatus.APPROVED
                        if (
                            settings.cmo_auto_approve_smm
                            if agent == DepartmentAgent.SMM
                            else settings.cmo_auto_approve_seo
                        )
                        else TaskStatus.PENDING_CMO_APPROVAL
                    )
                await db.create_task(
                    DepartmentTaskRecord(
                        agent=agent,
                        task_type=str(item.get("task_type", "content")),
                        priority=int(item.get("priority", 5)),
                        status=status,
                        brief=str(item.get("brief", data.get("strategy_summary", "")))[:2000],
                        input_json={"source": "cursor", "strategy": data.get("strategy_summary", "")},
                    )
                )
                stats["cmo_plans"] += 1

        elif kind == "content":
            post = ContentPostRecord(
                task_id=data.get("task_id"),
                platform=str(data.get("platform", "telegram")),
                title=str(data.get("title", "")),
                body=str(data.get("body", "")),
                status=ContentStatus.SCHEDULED,
            )
            await db.create_content_post(post)
            stats["content"] += 1

        elif kind == "analytics":
            report_date = data.get("report_date") or datetime.utcnow().strftime("%Y-%m-%d")
            existing = await db.get_latest_report()
            kpi = existing.kpi if existing and existing.report_date == report_date else None
            if kpi is None:
                from scout.department.kpi import build_kpi_snapshot

                kpi = await build_kpi_snapshot()
            report = DailyReportRecord(
                report_date=report_date,
                kpi=kpi,
                recommendations=list(data.get("recommendations", [])),
                summary=str(data.get("summary", "")),
                raw_json=data,
            )
            await db.save_daily_report(report)
            stats["analytics"] += 1

        elif kind == "ad_creative":
            creative = AdCreativeRecord(
                task_id=data.get("task_id"),
                headlines=list(data.get("headlines", [])),
                body=str(data.get("body", "")),
                audience=str(data.get("audience", "")),
                ab_hypothesis=str(data.get("ab_hypothesis", "")),
                status=AdCreativeStatus.PENDING_APPROVAL,
            )
            await db.create_ad_creative(creative)
            stats["ads"] += 1

        mark_handoff_done(path)

    return stats
