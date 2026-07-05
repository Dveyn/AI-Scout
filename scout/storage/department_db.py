from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import aiosqlite

from scout.config import get_settings
from scout.department.models import (
    AdCreativeRecord,
    AdCreativeStatus,
    AgentLogRecord,
    ContentPostRecord,
    ContentStatus,
    DailyReportRecord,
    DealRecord,
    DealStatus,
    DepartmentAgent,
    DepartmentTaskRecord,
    KpiSnapshot,
    TaskStatus,
)
from scout.storage.db import _db_path, _parse_dt

logger = logging.getLogger(__name__)

DEPARTMENT_TABLES = """
CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    lead_id TEXT,
    company_name TEXT NOT NULL DEFAULT '',
    contact_email TEXT,
    contact_phone TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT DEFAULT '',
    proposal_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS department_tasks (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    task_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    status TEXT NOT NULL DEFAULT 'pending',
    brief TEXT DEFAULT '',
    input_json TEXT DEFAULT '{}',
    output_json TEXT DEFAULT '{}',
    requires_approval INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    input_preview TEXT DEFAULT '',
    output_preview TEXT DEFAULT '',
    cost_rub REAL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL,
    kpi_json TEXT NOT NULL,
    recommendations_json TEXT DEFAULT '[]',
    summary TEXT DEFAULT '',
    raw_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_posts (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    platform TEXT NOT NULL,
    title TEXT DEFAULT '',
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_creatives (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    headlines_json TEXT DEFAULT '[]',
    body TEXT DEFAULT '',
    audience TEXT DEFAULT '',
    ab_hypothesis TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
"""


async def init_department_tables() -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.executescript(DEPARTMENT_TABLES)
        await conn.commit()


# --- Deals ---

async def create_deal(deal: DealRecord) -> DealRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO deals (id, lead_id, company_name, contact_email, contact_phone,
                status, notes, proposal_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deal.id,
                deal.lead_id,
                deal.company_name,
                deal.contact_email,
                deal.contact_phone,
                deal.status.value,
                deal.notes,
                deal.proposal_json,
                deal.created_at.isoformat(),
                deal.updated_at.isoformat(),
            ),
        )
        await conn.commit()
    return deal


async def get_deal(deal_id: str) -> DealRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)) as cur:
            row = await cur.fetchone()
    return _deal_from_row(row) if row else None


async def list_deals(status: DealStatus | None = None, limit: int = 100) -> list[DealRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        if status:
            sql = "SELECT * FROM deals WHERE status = ? ORDER BY updated_at DESC LIMIT ?"
            params: tuple = (status.value, limit)
        else:
            sql = "SELECT * FROM deals ORDER BY updated_at DESC LIMIT ?"
            params = (limit,)
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [_deal_from_row(r) for r in rows]


async def update_deal_status(deal_id: str, status: DealStatus, notes: str | None = None) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_db_path()) as conn:
        if notes is not None:
            await conn.execute(
                "UPDATE deals SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
                (status.value, notes, now, deal_id),
            )
        else:
            await conn.execute(
                "UPDATE deals SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, deal_id),
            )
        await conn.commit()


async def update_deal_proposal(deal_id: str, proposal_json: str) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "UPDATE deals SET proposal_json = ?, status = ?, updated_at = ? WHERE id = ?",
            (proposal_json, DealStatus.IN_PROGRESS.value, now, deal_id),
        )
        await conn.commit()


def _deal_from_row(row: aiosqlite.Row) -> DealRecord:
    return DealRecord(
        id=row["id"],
        lead_id=row["lead_id"],
        company_name=row["company_name"] or "",
        contact_email=row["contact_email"],
        contact_phone=row["contact_phone"],
        status=DealStatus(row["status"]),
        notes=row["notes"] or "",
        proposal_json=row["proposal_json"],
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
        updated_at=_parse_dt(row["updated_at"]) or datetime.utcnow(),
    )


# --- Tasks ---

async def create_task(task: DepartmentTaskRecord) -> DepartmentTaskRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO department_tasks (
                id, agent, task_type, priority, status, brief,
                input_json, output_json, requires_approval, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.agent.value,
                task.task_type,
                task.priority,
                task.status.value,
                task.brief,
                json.dumps(task.input_json, ensure_ascii=False),
                json.dumps(task.output_json, ensure_ascii=False),
                int(task.requires_approval),
                task.created_at.isoformat(),
                task.completed_at.isoformat() if task.completed_at else None,
            ),
        )
        await conn.commit()
    return task


async def list_tasks(
    status: TaskStatus | None = None,
    agent: DepartmentAgent | None = None,
    limit: int = 50,
) -> list[DepartmentTaskRecord]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status.value)
    if agent:
        clauses.append("agent = ?")
        params.append(agent.value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            f"SELECT * FROM department_tasks {where} ORDER BY priority ASC, created_at DESC LIMIT ?",
            tuple(params),
        ) as cur:
            rows = await cur.fetchall()
    return [_task_from_row(r) for r in rows]


async def update_task(task: DepartmentTaskRecord) -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            UPDATE department_tasks SET
                status = ?, output_json = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                task.status.value,
                json.dumps(task.output_json, ensure_ascii=False),
                task.completed_at.isoformat() if task.completed_at else None,
                task.id,
            ),
        )
        await conn.commit()


async def approve_task(task_id: str) -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "UPDATE department_tasks SET status = ? WHERE id = ?",
            (TaskStatus.APPROVED.value, task_id),
        )
        await conn.commit()


async def reject_task(task_id: str) -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "UPDATE department_tasks SET status = ? WHERE id = ?",
            (TaskStatus.REJECTED.value, task_id),
        )
        await conn.commit()


def _task_from_row(row: aiosqlite.Row) -> DepartmentTaskRecord:
    return DepartmentTaskRecord(
        id=row["id"],
        agent=DepartmentAgent(row["agent"]),
        task_type=row["task_type"],
        priority=row["priority"],
        status=TaskStatus(row["status"]),
        brief=row["brief"] or "",
        input_json=json.loads(row["input_json"] or "{}"),
        output_json=json.loads(row["output_json"] or "{}"),
        requires_approval=bool(row["requires_approval"]),
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
        completed_at=_parse_dt(row["completed_at"]) if row["completed_at"] else None,
    )


# --- Agent logs ---

async def log_agent_action(
    agent: str,
    action: str,
    input_preview: str = "",
    output_preview: str = "",
    cost_rub: float = 0.0,
) -> AgentLogRecord:
    log = AgentLogRecord(
        agent=DepartmentAgent(agent) if agent in {a.value for a in DepartmentAgent} else DepartmentAgent.ANALYTICS,
        action=action,
        input_preview=input_preview,
        output_preview=output_preview,
        cost_rub=cost_rub,
    )
    if agent in {a.value for a in DepartmentAgent}:
        log.agent = DepartmentAgent(agent)
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO agent_logs (id, agent, action, input_preview, output_preview, cost_rub, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.id,
                agent,
                action,
                input_preview[:1000],
                output_preview[:2000],
                cost_rub,
                log.created_at.isoformat(),
            ),
        )
        await conn.commit()
    return log


async def list_agent_logs(agent: str | None = None, limit: int = 100) -> list[AgentLogRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        if agent:
            sql = "SELECT * FROM agent_logs WHERE agent = ? ORDER BY created_at DESC LIMIT ?"
            params: tuple = (agent, limit)
        else:
            sql = "SELECT * FROM agent_logs ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [
        AgentLogRecord(
            id=r["id"],
            agent=DepartmentAgent(r["agent"]),
            action=r["action"],
            input_preview=r["input_preview"] or "",
            output_preview=r["output_preview"] or "",
            cost_rub=r["cost_rub"] or 0.0,
            created_at=_parse_dt(r["created_at"]) or datetime.utcnow(),
        )
        for r in rows
    ]


# --- Daily reports ---

async def save_daily_report(report: DailyReportRecord) -> DailyReportRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO daily_reports (
                id, report_date, kpi_json, recommendations_json, summary, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.id,
                report.report_date,
                report.kpi.model_dump_json(),
                json.dumps(report.recommendations, ensure_ascii=False),
                report.summary,
                json.dumps(report.raw_json, ensure_ascii=False),
                report.created_at.isoformat(),
            ),
        )
        await conn.commit()
    return report


async def get_latest_report() -> DailyReportRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return DailyReportRecord(
        id=row["id"],
        report_date=row["report_date"],
        kpi=KpiSnapshot.model_validate_json(row["kpi_json"]),
        recommendations=json.loads(row["recommendations_json"] or "[]"),
        summary=row["summary"] or "",
        raw_json=json.loads(row["raw_json"] or "{}"),
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
    )


async def list_daily_reports(limit: int = 30) -> list[DailyReportRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [
        DailyReportRecord(
            id=r["id"],
            report_date=r["report_date"],
            kpi=KpiSnapshot.model_validate_json(r["kpi_json"]),
            recommendations=json.loads(r["recommendations_json"] or "[]"),
            summary=r["summary"] or "",
            raw_json=json.loads(r["raw_json"] or "{}"),
            created_at=_parse_dt(r["created_at"]) or datetime.utcnow(),
        )
        for r in rows
    ]


# --- Content posts ---

async def create_content_post(post: ContentPostRecord) -> ContentPostRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO content_posts (
                id, task_id, platform, title, body, status, scheduled_at, published_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.id,
                post.task_id,
                post.platform,
                post.title,
                post.body,
                post.status.value,
                post.scheduled_at.isoformat() if post.scheduled_at else None,
                post.published_at.isoformat() if post.published_at else None,
                post.created_at.isoformat(),
            ),
        )
        await conn.commit()
    return post


async def list_content_posts(limit: int = 50) -> list[ContentPostRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM content_posts ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [_content_from_row(r) for r in rows]


async def update_content_status(
    post_id: str, status: ContentStatus, published_at: datetime | None = None
) -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "UPDATE content_posts SET status = ?, published_at = ? WHERE id = ?",
            (
                status.value,
                published_at.isoformat() if published_at else None,
                post_id,
            ),
        )
        await conn.commit()


def _content_from_row(row: aiosqlite.Row) -> ContentPostRecord:
    return ContentPostRecord(
        id=row["id"],
        task_id=row["task_id"],
        platform=row["platform"],
        title=row["title"] or "",
        body=row["body"],
        status=ContentStatus(row["status"]),
        scheduled_at=_parse_dt(row["scheduled_at"]) if row["scheduled_at"] else None,
        published_at=_parse_dt(row["published_at"]) if row["published_at"] else None,
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
    )


# --- Ad creatives ---

async def create_ad_creative(creative: AdCreativeRecord) -> AdCreativeRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO ad_creatives (
                id, task_id, headlines_json, body, audience, ab_hypothesis, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                creative.id,
                creative.task_id,
                json.dumps(creative.headlines, ensure_ascii=False),
                creative.body,
                creative.audience,
                creative.ab_hypothesis,
                creative.status.value,
                creative.created_at.isoformat(),
            ),
        )
        await conn.commit()
    return creative


async def list_ad_creatives(status: AdCreativeStatus | None = None, limit: int = 50) -> list[AdCreativeRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        if status:
            sql = "SELECT * FROM ad_creatives WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            params: tuple = (status.value, limit)
        else:
            sql = "SELECT * FROM ad_creatives ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [_ad_from_row(r) for r in rows]


async def update_ad_creative_status(creative_id: str, status: AdCreativeStatus) -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "UPDATE ad_creatives SET status = ? WHERE id = ?",
            (status.value, creative_id),
        )
        await conn.commit()


async def get_ad_creative(creative_id: str) -> AdCreativeRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM ad_creatives WHERE id = ?", (creative_id,)) as cur:
            row = await cur.fetchone()
    return _ad_from_row(row) if row else None


def _ad_from_row(row: aiosqlite.Row) -> AdCreativeRecord:
    return AdCreativeRecord(
        id=row["id"],
        task_id=row["task_id"],
        headlines=json.loads(row["headlines_json"] or "[]"),
        body=row["body"] or "",
        audience=row["audience"] or "",
        ab_hypothesis=row["ab_hypothesis"] or "",
        status=AdCreativeStatus(row["status"]),
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
    )


# --- KPI helpers ---

async def count_deals_by_status() -> dict[str, int]:
    async with aiosqlite.connect(_db_path()) as conn:
        async with conn.execute(
            "SELECT status, COUNT(*) as c FROM deals GROUP BY status"
        ) as cur:
            rows = await cur.fetchall()
    return {row[0]: row[1] for row in rows}


async def count_leads_period(days: int = 1) -> dict[str, int]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(_db_path()) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM leads WHERE created_at >= ?", (since,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with conn.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE created_at >= ?
            AND agent_result_json IS NOT NULL
            AND json_extract(agent_result_json, '$.is_target') = 1
            """,
            (since,),
        ) as cur:
            targets = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT COUNT(*) FROM leads WHERE created_at >= ? AND send_status = 'sent'",
            (since,),
        ) as cur:
            sent = (await cur.fetchone())[0]
    return {"total": total or 0, "targets": targets or 0, "sent": sent or 0}


async def get_department_stats() -> dict[str, Any]:
    deals = await count_deals_by_status()
    tasks = await list_tasks(limit=200)
    pending_ads = await list_ad_creatives(status=AdCreativeStatus.PENDING_APPROVAL)
    pending_cmo = [t for t in tasks if t.status == TaskStatus.PENDING_CMO_APPROVAL]
    latest = await get_latest_report()
    return {
        "deals": deals,
        "tasks_active": len([t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.APPROVED)]),
        "pending_ads": len(pending_ads),
        "pending_cmo": len(pending_cmo),
        "latest_report": latest,
    }
