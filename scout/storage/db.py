from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from scout.config import get_settings
from scout.models.contacts import LeadContacts, OutreachChannel
from scout.models.schemas import (
    AgentResult,
    AgentTraceStep,
    DashboardStats,
    FollowupMessage,
    JobCreate,
    JobRecord,
    JobReport,
    JobStatus,
    LeadRecord,
    OutreachLogEntry,
    RawLead,
    SendStatus,
    Tone,
)
from scout.outreach.dedup import hash_key
from scout.storage.company_dedup import company_keys


def _db_path() -> Path:
    url = get_settings().database_url
    path = url.split("///", 1)[-1]
    return Path(path)


async def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                icp TEXT NOT NULL,
                product TEXT NOT NULL,
                offer TEXT,
                query TEXT NOT NULL,
                city TEXT NOT NULL,
                limit_count INTEGER NOT NULL,
                tone TEXT NOT NULL,
                auto_send INTEGER DEFAULT 0,
                agent_skill TEXT,
                preset TEXT,
                generate_followups INTEGER DEFAULT 1,
                status TEXT NOT NULL,
                progress_current INTEGER DEFAULT 0,
                progress_total INTEGER DEFAULT 0,
                llm_cost_rub REAL DEFAULT 0,
                error TEXT,
                report_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                agent_result_json TEXT,
                agent_trace_json TEXT,
                website_audit_json TEXT,
                email TEXT,
                fit_score INTEGER,
                llm_cost_rub REAL DEFAULT 0,
                send_status TEXT,
                send_error TEXT,
                sent_at TEXT,
                fallback_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS sent_contacts (
                contact_key TEXT PRIMARY KEY,
                email TEXT,
                phone TEXT,
                company_name TEXT,
                lead_id TEXT,
                job_id TEXT,
                sent_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outreach_log (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                lead_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                channel TEXT NOT NULL,
                subject TEXT,
                message_preview TEXT,
                touch_number INTEGER DEFAULT 1,
                status TEXT NOT NULL,
                error TEXT,
                sent_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scanned_companies (
                company_key TEXT PRIMARY KEY,
                company_name TEXT,
                lead_id TEXT,
                job_id TEXT,
                scanned_at TEXT NOT NULL
            );
            """
        )
        await _backfill_scanned_companies(db)
        for stmt in (
            "ALTER TABLE jobs ADD COLUMN offer TEXT",
            "ALTER TABLE jobs ADD COLUMN auto_send INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN report_json TEXT",
            "ALTER TABLE leads ADD COLUMN website_audit_json TEXT",
            "ALTER TABLE leads ADD COLUMN email TEXT",
            "ALTER TABLE leads ADD COLUMN send_status TEXT",
            "ALTER TABLE leads ADD COLUMN send_error TEXT",
            "ALTER TABLE leads ADD COLUMN sent_at TEXT",
            "ALTER TABLE leads ADD COLUMN fallback_text TEXT",
            "ALTER TABLE leads ADD COLUMN contacts_json TEXT",
            "ALTER TABLE leads ADD COLUMN outreach_channels_json TEXT",
            "ALTER TABLE leads ADD COLUMN followups_json TEXT",
            "ALTER TABLE leads ADD COLUMN sequence_touch_sent INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN agent_skill TEXT",
            "ALTER TABLE jobs ADD COLUMN preset TEXT",
            "ALTER TABLE jobs ADD COLUMN generate_followups INTEGER DEFAULT 1",
            "ALTER TABLE outreach_log ADD COLUMN touch_number INTEGER DEFAULT 1",
        ):
            try:
                await db.execute(stmt)
            except Exception:
                pass
        await db.commit()

    from scout.storage.department_db import init_department_tables

    await init_department_tables()


async def _backfill_scanned_companies(db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM scanned_companies")
    async with db.execute("SELECT id, job_id, raw_json, created_at FROM leads") as cur:
        rows = await cur.fetchall()
    for lead_id, job_id, raw_json, created_at in rows:
        try:
            raw = RawLead.model_validate_json(raw_json)
        except Exception:
            continue
        for key in company_keys(raw):
            await db.execute(
                """
                INSERT OR IGNORE INTO scanned_companies (
                    company_key, company_name, lead_id, job_id, scanned_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (key, raw.name, lead_id, job_id, created_at),
            )
    await db.commit()


async def list_scanned_company_keys() -> set[str]:
    async with aiosqlite.connect(_db_path()) as db:
        async with db.execute("SELECT company_key FROM scanned_companies") as cur:
            rows = await cur.fetchall()
    return {row[0] for row in rows}


async def clear_all_data() -> dict[str, int]:
    """Delete all campaigns, leads, scans and outreach history."""
    tables = (
        "leads",
        "jobs",
        "scanned_companies",
        "outreach_log",
        "sent_contacts",
        "deals",
        "department_tasks",
        "agent_logs",
        "daily_reports",
        "content_posts",
        "ad_creatives",
    )
    counts: dict[str, int] = {}
    async with aiosqlite.connect(_db_path()) as db:
        for table in tables:
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                row = await cur.fetchone()
                counts[table] = int(row[0]) if row else 0
            await db.execute(f"DELETE FROM {table}")
        await db.commit()
    return counts


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _job_from_row(row: aiosqlite.Row) -> JobRecord:
    report = None
    try:
        if row["report_json"]:
            report = JobReport.model_validate_json(row["report_json"])
    except (KeyError, TypeError):
        pass
    return JobRecord(
        id=row["id"],
        icp=row["icp"],
        product=row["product"],
        offer=row["offer"] if "offer" in row.keys() else None,
        query=row["query"],
        city=row["city"],
        limit=row["limit_count"],
        tone=Tone(row["tone"]),
        auto_send=bool(row["auto_send"]) if "auto_send" in row.keys() else False,
        agent_skill=row["agent_skill"] if "agent_skill" in row.keys() else None,
        preset=row["preset"] if "preset" in row.keys() else None,
        generate_followups=bool(row["generate_followups"]) if "generate_followups" in row.keys() else True,
        status=JobStatus(row["status"]),
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        llm_cost_rub=row["llm_cost_rub"],
        error=row["error"],
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
    )


async def create_job(payload: JobCreate) -> JobRecord:
    job = JobRecord(
        icp=payload.icp,
        product=payload.product,
        offer=payload.offer,
        query=payload.query,
        city=payload.city,
        limit=payload.limit,
        tone=payload.tone,
        auto_send=payload.auto_send,
        agent_skill=payload.agent_skill,
        preset=payload.preset,
        generate_followups=payload.generate_followups,
    )
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO jobs (
                id, icp, product, offer, query, city, limit_count, tone, auto_send,
                agent_skill, preset, generate_followups,
                status, progress_current, progress_total, llm_cost_rub, error, report_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.icp,
                job.product,
                job.offer,
                job.query,
                job.city,
                job.limit,
                job.tone.value,
                int(job.auto_send),
                job.agent_skill,
                job.preset,
                int(job.generate_followups),
                job.status.value,
                job.progress_current,
                job.progress_total,
                job.llm_cost_rub,
                job.error,
                None,
                job.created_at.isoformat(),
            ),
        )
        await db.commit()
    return job


async def update_job(job: JobRecord) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            UPDATE jobs SET
                status = ?, progress_current = ?, progress_total = ?,
                llm_cost_rub = ?, error = ?
            WHERE id = ?
            """,
            (
                job.status.value,
                job.progress_current,
                job.progress_total,
                job.llm_cost_rub,
                job.error,
                job.id,
            ),
        )
        await db.commit()


async def update_job_report(job_id: str, report: JobReport) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "UPDATE jobs SET report_json = ? WHERE id = ?",
            (report.model_dump_json(), job_id),
        )
        await db.commit()


async def get_job(job_id: str) -> JobRecord | None:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return _job_from_row(row)


async def list_jobs(limit: int = 50) -> list[JobRecord]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [_job_from_row(row) for row in rows]


async def get_job_report(job_id: str) -> JobReport | None:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT report_json FROM jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
    if not row or not row["report_json"]:
        return None
    return JobReport.model_validate_json(row["report_json"])


def _lead_from_row(row: aiosqlite.Row) -> LeadRecord:
    trace_data = json.loads(row["agent_trace_json"] or "[]")
    audit_data = None
    if row["website_audit_json"]:
        audit_data = json.loads(row["website_audit_json"])
    result = None
    if row["agent_result_json"]:
        result = AgentResult.model_validate_json(row["agent_result_json"])
    send_status = None
    if row["send_status"]:
        send_status = SendStatus(row["send_status"])
    contacts = None
    try:
        if row["contacts_json"]:
            contacts = LeadContacts.model_validate_json(row["contacts_json"])
    except (KeyError, TypeError):
        pass
    outreach_channels: list[OutreachChannel] = []
    try:
        if row["outreach_channels_json"]:
            data = json.loads(row["outreach_channels_json"])
            outreach_channels = [OutreachChannel.model_validate(c) for c in data]
    except (KeyError, TypeError, json.JSONDecodeError):
        pass
    followups: list[FollowupMessage] = []
    try:
        if row["followups_json"]:
            data = json.loads(row["followups_json"])
            followups = [FollowupMessage.model_validate(item) for item in data]
    except (KeyError, TypeError, json.JSONDecodeError):
        pass
    sequence_touch_sent = 0
    try:
        if row["sequence_touch_sent"] is not None:
            sequence_touch_sent = int(row["sequence_touch_sent"])
    except (KeyError, TypeError):
        pass
    return LeadRecord(
        id=row["id"],
        job_id=row["job_id"],
        raw=RawLead.model_validate_json(row["raw_json"]),
        result=result,
        trace=[AgentTraceStep.model_validate(t) for t in trace_data],
        website_audit=audit_data,
        email=row["email"],
        fit_score=row["fit_score"],
        llm_cost_rub=row["llm_cost_rub"],
        send_status=send_status,
        send_error=row["send_error"],
        sent_at=_parse_dt(row["sent_at"]),
        fallback_text=row["fallback_text"],
        contacts=contacts,
        outreach_channels=outreach_channels,
        followups=followups,
        sequence_touch_sent=sequence_touch_sent,
        created_at=_parse_dt(row["created_at"]) or datetime.utcnow(),
    )


async def save_lead(lead: LeadRecord) -> None:
    keys = company_keys(lead.raw)
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO leads (
                id, job_id, raw_json, agent_result_json, agent_trace_json,
                website_audit_json, email, fit_score, llm_cost_rub,
                send_status, send_error, sent_at, fallback_text,
                contacts_json, outreach_channels_json, followups_json, sequence_touch_sent,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead.id,
                lead.job_id,
                lead.raw.model_dump_json(),
                lead.result.model_dump_json() if lead.result else None,
                json.dumps([t.model_dump() for t in lead.trace], ensure_ascii=False),
                json.dumps(lead.website_audit, ensure_ascii=False) if lead.website_audit else None,
                lead.email or lead.raw.email,
                lead.fit_score,
                lead.llm_cost_rub,
                lead.send_status.value if lead.send_status else None,
                lead.send_error,
                lead.sent_at.isoformat() if lead.sent_at else None,
                lead.fallback_text,
                lead.contacts.model_dump_json() if lead.contacts else None,
                json.dumps([c.model_dump() for c in lead.outreach_channels], ensure_ascii=False)
                if lead.outreach_channels
                else None,
                json.dumps([f.model_dump(mode="json") for f in lead.followups], ensure_ascii=False)
                if lead.followups
                else None,
                lead.sequence_touch_sent,
                lead.created_at.isoformat(),
            ),
        )
        for key in keys:
            await db.execute(
                """
                INSERT OR IGNORE INTO scanned_companies (
                    company_key, company_name, lead_id, job_id, scanned_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    key,
                    lead.raw.name,
                    lead.id,
                    lead.job_id,
                    lead.created_at.isoformat(),
                ),
            )
        await db.commit()


async def update_lead(lead: LeadRecord) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            UPDATE leads SET
                email = ?, send_status = ?, send_error = ?, sent_at = ?, fallback_text = ?,
                outreach_channels_json = ?, followups_json = ?, sequence_touch_sent = ?
            WHERE id = ?
            """,
            (
                lead.email or lead.raw.email,
                lead.send_status.value if lead.send_status else None,
                lead.send_error,
                lead.sent_at.isoformat() if lead.sent_at else None,
                lead.fallback_text,
                json.dumps([c.model_dump() for c in lead.outreach_channels], ensure_ascii=False)
                if lead.outreach_channels
                else None,
                json.dumps([f.model_dump(mode="json") for f in lead.followups], ensure_ascii=False)
                if lead.followups
                else None,
                lead.sequence_touch_sent,
                lead.id,
            ),
        )
        await db.commit()


async def update_lead_result(lead: LeadRecord) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            UPDATE leads SET
                agent_result_json = ?, outreach_channels_json = ?, fit_score = ?,
                followups_json = ?, sequence_touch_sent = ?
            WHERE id = ?
            """,
            (
                lead.result.model_dump_json() if lead.result else None,
                json.dumps([c.model_dump() for c in lead.outreach_channels], ensure_ascii=False)
                if lead.outreach_channels
                else None,
                lead.fit_score,
                json.dumps([f.model_dump(mode="json") for f in lead.followups], ensure_ascii=False)
                if lead.followups
                else None,
                lead.sequence_touch_sent,
                lead.id,
            ),
        )
        await db.commit()


async def get_lead(lead_id: str) -> LeadRecord | None:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return _lead_from_row(row)


async def list_leads(job_id: str) -> list[LeadRecord]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads WHERE job_id = ? ORDER BY created_at",
            (job_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [_lead_from_row(row) for row in rows]


async def list_leads_for_followup() -> list[LeadRecord]:
    """Лиды с отправленным первым касанием и незавершённой цепочкой follow-up."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM leads
            WHERE send_status = 'sent'
              AND followups_json IS NOT NULL
              AND followups_json != '[]'
              AND sequence_touch_sent >= 1
              AND sequence_touch_sent < 3
            ORDER BY sent_at
            """
        ) as cur:
            rows = await cur.fetchall()
    return [_lead_from_row(row) for row in rows]


async def list_recent_sent_emails(days: int = 21) -> list[dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT email, company_name, lead_id, job_id, sent_at
            FROM sent_contacts
            WHERE email IS NOT NULL AND email != ''
              AND sent_at >= datetime('now', ?)
            ORDER BY sent_at DESC
            """,
            (f"-{days} days",),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def list_ready_leads(limit: int = 20) -> list[LeadRecord]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM leads
            WHERE send_status = 'ready'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [_lead_from_row(row) for row in rows]


async def was_contact_sent(key: str) -> bool:
    async with aiosqlite.connect(_db_path()) as db:
        async with db.execute(
            "SELECT 1 FROM sent_contacts WHERE contact_key = ?",
            (hash_key(key),),
        ) as cur:
            row = await cur.fetchone()
    return row is not None


async def mark_contact_sent(key: str, lead: LeadRecord) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO sent_contacts (
                contact_key, email, phone, company_name, lead_id, job_id, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hash_key(key),
                lead.email or lead.raw.email,
                lead.raw.phone,
                lead.raw.name,
                lead.id,
                lead.job_id,
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()


async def log_outreach(
    lead: LeadRecord,
    *,
    channel: str,
    status: SendStatus,
    error: str | None = None,
    touch_number: int = 1,
    subject: str | None = None,
    message_preview: str | None = None,
) -> None:
    preview = message_preview
    if preview is None and lead.result and lead.result.message:
        preview = lead.result.message[:200]
    subj = subject
    if subj is None and lead.result:
        subj = lead.result.subject
    entry = OutreachLogEntry(
        job_id=lead.job_id,
        lead_id=lead.id,
        company_name=lead.raw.name,
        email=lead.email or lead.raw.email,
        phone=lead.raw.phone,
        channel=channel,
        subject=subj,
        message_preview=preview,
        touch_number=touch_number,
        status=status,
        error=error,
    )
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO outreach_log (
                id, job_id, lead_id, company_name, email, phone, channel,
                subject, message_preview, touch_number, status, error, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.job_id,
                entry.lead_id,
                entry.company_name,
                entry.email,
                entry.phone,
                entry.channel,
                entry.subject,
                entry.message_preview,
                entry.touch_number,
                entry.status.value,
                entry.error,
                entry.sent_at.isoformat(),
            ),
        )
        await db.commit()


async def list_outreach_log(limit: int = 100) -> list[OutreachLogEntry]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM outreach_log ORDER BY sent_at DESC LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()

    entries: list[OutreachLogEntry] = []
    for row in rows:
        entries.append(
            OutreachLogEntry(
                id=row["id"],
                job_id=row["job_id"],
                lead_id=row["lead_id"],
                company_name=row["company_name"],
                email=row["email"],
                phone=row["phone"],
                channel=row["channel"],
                subject=row["subject"],
                message_preview=row["message_preview"],
                touch_number=row["touch_number"] if "touch_number" in row.keys() else 1,
                status=SendStatus(row["status"]),
                error=row["error"],
                sent_at=_parse_dt(row["sent_at"]) or datetime.utcnow(),
            )
        )
    return entries


async def get_dashboard_stats() -> DashboardStats:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT COUNT(*) AS c FROM jobs") as cur:
            total_jobs = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) AS c FROM leads") as cur:
            total_leads = (await cur.fetchone())["c"]

        async with db.execute(
            """
            SELECT
                SUM(CASE WHEN agent_result_json IS NOT NULL
                    AND json_extract(agent_result_json, '$.is_target') = 1 THEN 1 ELSE 0 END) AS targets,
                SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) AS emails_found,
                SUM(CASE WHEN send_status = 'sent' THEN 1 ELSE 0 END) AS emails_sent,
                SUM(CASE WHEN send_status = 'no_email' THEN 1 ELSE 0 END) AS no_email,
                SUM(CASE WHEN send_status = 'failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN send_status = 'duplicate' THEN 1 ELSE 0 END) AS duplicates
            FROM leads
            """
        ) as cur:
            agg = await cur.fetchone()

        async with db.execute("SELECT COALESCE(SUM(llm_cost_rub), 0) AS s FROM jobs") as cur:
            llm_cost = (await cur.fetchone())["s"]

    return DashboardStats(
        total_jobs=total_jobs or 0,
        total_leads=total_leads or 0,
        total_targets=agg["targets"] or 0,
        emails_found=agg["emails_found"] or 0,
        emails_sent=agg["emails_sent"] or 0,
        no_email=agg["no_email"] or 0,
        failed=agg["failed"] or 0,
        duplicates=agg["duplicates"] or 0,
        total_llm_cost_rub=llm_cost or 0.0,
    )
