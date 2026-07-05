from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from office.config import OFFICE_ROOT, get_office_settings
from office.models import (
    ActivityRecord,
    AgentStatus,
    BudgetRecord,
    DepartmentRecord,
    DirectiveRecord,
    DirectiveStatus,
    GoalHorizon,
    GoalRecord,
    GoalStatus,
    MeetingItemRecord,
    MeetingRecord,
    MeetingStatus,
    ModelTier,
    OnlineEventRecord,
    WorkstationRecord,
)

logger = logging.getLogger(__name__)

OFFICE_TABLES = """
CREATE TABLE IF NOT EXISTS departments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    head_role TEXT DEFAULT '',
    description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workstations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    preset_id TEXT DEFAULT '',
    department_slug TEXT NOT NULL,
    role TEXT NOT NULL,
    model_tier TEXT NOT NULL DEFAULT 'execution',
    custom_prompt TEXT DEFAULT '',
    skills_json TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'idle',
    current_task TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    horizon TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    owner_department TEXT DEFAULT '',
    parent_goal_id TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Standup',
    agenda TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'scheduled',
    participants_json TEXT DEFAULT '[]',
    transcript_summary TEXT DEFAULT '',
    decisions_json TEXT DEFAULT '[]',
    kpi_snapshot_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS meeting_items (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    department_slug TEXT NOT NULL,
    head_role TEXT NOT NULL,
    report TEXT DEFAULT '',
    blockers TEXT DEFAULT '',
    plan TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS office_budget (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    scope_id TEXT DEFAULT '',
    limit_rub REAL DEFAULT 0,
    spent_rub REAL DEFAULT 0,
    period TEXT DEFAULT 'day'
);

CREATE TABLE IF NOT EXISTS workstation_activity (
    id TEXT PRIMARY KEY,
    workstation_id TEXT NOT NULL,
    step TEXT NOT NULL,
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS online_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    event_type TEXT DEFAULT 'other',
    date_hint TEXT DEFAULT '',
    audience TEXT DEFAULT '',
    relevance INTEGER DEFAULT 5,
    why_relevant TEXT DEFAULT '',
    registration_hint TEXT DEFAULT '',
    source_brief TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS directives (
    id TEXT PRIMARY KEY,
    brief TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planning',
    coo_plan TEXT DEFAULT '',
    schedule_json TEXT DEFAULT '[]',
    dept_results_json TEXT DEFAULT '[]',
    final_report TEXT DEFAULT '',
    cost_rub REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""

DEFAULT_DEPARTMENTS = [
    ("dept-exec", "Управление", "executive", "COO", "Стратегия и приоритеты"),
    ("dept-mkt", "Маркетинг", "marketing", "CMO", "Контент, SEO, реклама"),
    ("dept-sales", "Продажи", "sales", "Head of Sales", "Воронка и КП"),
    ("dept-leadgen", "Лидоген", "leadgen", "Head of LeadGen", "Scout и ICP"),
    ("dept-prod", "Продакшн", "production", "Head of Production", "Проекты и разработка"),
]


def _db_path() -> Path:
    url = get_office_settings().office_database_url
    if url.startswith("sqlite"):
        raw = url.split("///", 1)[-1]
        return Path(raw)
    return OFFICE_ROOT / "data" / "office.db"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


async def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(OFFICE_TABLES)
        await _migrate_workstations(conn)
        await _migrate_directives(conn)
        for row in DEFAULT_DEPARTMENTS:
            await conn.execute(
                """
                INSERT OR IGNORE INTO departments (id, name, slug, head_role, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                row,
            )
        await conn.execute(
            """
            INSERT OR IGNORE INTO office_budget (id, scope, scope_id, limit_rub, spent_rub, period)
            VALUES ('budget-global', 'global', '', ?, 0, 'day')
            """,
            (get_office_settings().office_daily_budget_rub,),
        )
        await conn.commit()


async def _migrate_workstations(conn: aiosqlite.Connection) -> None:
    cols = await (await conn.execute("PRAGMA table_info(workstations)")).fetchall()
    names = {r[1] for r in cols}
    if "last_result" not in names:
        await conn.execute("ALTER TABLE workstations ADD COLUMN last_result TEXT DEFAULT ''")


async def _migrate_directives(conn: aiosqlite.Connection) -> None:
    cols = await (await conn.execute("PRAGMA table_info(directives)")).fetchall()
    names = {r[1] for r in cols}
    if "schedule_json" not in names:
        await conn.execute("ALTER TABLE directives ADD COLUMN schedule_json TEXT DEFAULT '[]'")


async def log_activity(workstation_id: str, step: str, message: str = "") -> ActivityRecord:
    from uuid import uuid4

    rec = ActivityRecord(
        id=str(uuid4()),
        workstation_id=workstation_id,
        step=step,
        message=message[:2000],
    )
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT INTO workstation_activity (id, workstation_id, step, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rec.id, rec.workstation_id, rec.step, rec.message, rec.created_at.isoformat()),
        )
        await conn.commit()
    return rec


async def list_activity(workstation_id: str, *, limit: int = 30) -> list[ActivityRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                """
                SELECT * FROM workstation_activity
                WHERE workstation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workstation_id, limit),
            )
        ).fetchall()
    return [
        ActivityRecord(
            id=r["id"],
            workstation_id=r["workstation_id"],
            step=r["step"],
            message=r["message"] or "",
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]


async def list_departments() -> list[DepartmentRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute("SELECT * FROM departments ORDER BY name")).fetchall()
    return [
        DepartmentRecord(
            id=r["id"],
            name=r["name"],
            slug=r["slug"],
            head_role=r["head_role"] or "",
            description=r["description"] or "",
        )
        for r in rows
    ]


def _workstation_from_row(r: aiosqlite.Row) -> WorkstationRecord:
    return WorkstationRecord(
        id=r["id"],
        name=r["name"],
        preset_id=r["preset_id"] or "",
        department_slug=r["department_slug"],
        role=r["role"],
        model_tier=ModelTier(r["model_tier"]),
        custom_prompt=r["custom_prompt"] or "",
        skills=json.loads(r["skills_json"] or "[]"),
        status=AgentStatus(r["status"]),
        current_task=r["current_task"] or "",
        last_result=(r["last_result"] if "last_result" in r.keys() else "") or "",
        created_at=datetime.fromisoformat(r["created_at"]),
    )


async def list_workstations() -> list[WorkstationRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute("SELECT * FROM workstations ORDER BY created_at")).fetchall()
    return [_workstation_from_row(r) for r in rows]


async def get_workstation(ws_id: str) -> WorkstationRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (
            await conn.execute("SELECT * FROM workstations WHERE id = ?", (ws_id,))
        ).fetchone()
    return _workstation_from_row(row) if row else None


async def get_workstation_by_preset(preset_id: str) -> WorkstationRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (
            await conn.execute(
                "SELECT * FROM workstations WHERE preset_id = ? ORDER BY created_at LIMIT 1",
                (preset_id,),
            )
        ).fetchone()
    return _workstation_from_row(row) if row else None


async def get_workstation_by_department_head(department_slug: str) -> WorkstationRecord | None:
    from office.crews.loader import head_preset_for_department

    preset = head_preset_for_department(department_slug)
    if not preset:
        return None
    return await get_workstation_by_preset(preset.id)


async def save_workstation(ws: WorkstationRecord) -> WorkstationRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO workstations
            (id, name, preset_id, department_slug, role, model_tier, custom_prompt,
             skills_json, status, current_task, last_result, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ws.id,
                ws.name,
                ws.preset_id,
                ws.department_slug,
                ws.role,
                ws.model_tier.value,
                ws.custom_prompt,
                json.dumps(ws.skills, ensure_ascii=False),
                ws.status.value,
                ws.current_task,
                ws.last_result,
                ws.created_at.isoformat(),
            ),
        )
        await conn.commit()
    return ws


async def update_workstation_status(
    ws_id: str,
    status: AgentStatus,
    *,
    current_task: str | None = None,
) -> None:
    ws = await get_workstation(ws_id)
    if not ws:
        return
    ws.status = status
    if current_task is not None:
        ws.current_task = current_task
    await save_workstation(ws)


async def list_goals(*, horizon: GoalHorizon | None = None) -> list[GoalRecord]:
    query = "SELECT * FROM goals"
    params: tuple[Any, ...] = ()
    if horizon:
        query += " WHERE horizon = ?"
        params = (horizon.value,)
    query += " ORDER BY created_at DESC"
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute(query, params)).fetchall()
    return [
        GoalRecord(
            id=r["id"],
            horizon=GoalHorizon(r["horizon"]),
            text=r["text"],
            status=GoalStatus(r["status"]),
            owner_department=r["owner_department"] or "",
            parent_goal_id=r["parent_goal_id"],
            created_at=datetime.fromisoformat(r["created_at"]),
            completed_at=_parse_dt(r["completed_at"]),
        )
        for r in rows
    ]


async def save_goal(goal: GoalRecord) -> GoalRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO goals
            (id, horizon, text, status, owner_department, parent_goal_id, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal.id,
                goal.horizon.value,
                goal.text,
                goal.status.value,
                goal.owner_department,
                goal.parent_goal_id,
                goal.created_at.isoformat(),
                goal.completed_at.isoformat() if goal.completed_at else None,
            ),
        )
        await conn.commit()
    return goal


async def save_meeting(meeting: MeetingRecord) -> MeetingRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO meetings
            (id, title, agenda, status, participants_json, transcript_summary,
             decisions_json, kpi_snapshot_json, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting.id,
                meeting.title,
                meeting.agenda,
                meeting.status.value,
                json.dumps(meeting.participants, ensure_ascii=False),
                meeting.transcript_summary,
                json.dumps(meeting.decisions, ensure_ascii=False),
                json.dumps(meeting.kpi_snapshot, ensure_ascii=False),
                meeting.created_at.isoformat(),
                meeting.completed_at.isoformat() if meeting.completed_at else None,
            ),
        )
        await conn.commit()
    return meeting


async def get_meeting(meeting_id: str) -> MeetingRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))).fetchone()
    if not row:
        return None
    return MeetingRecord(
        id=row["id"],
        title=row["title"],
        agenda=row["agenda"] or "",
        status=MeetingStatus(row["status"]),
        participants=json.loads(row["participants_json"] or "[]"),
        transcript_summary=row["transcript_summary"] or "",
        decisions=json.loads(row["decisions_json"] or "[]"),
        kpi_snapshot=json.loads(row["kpi_snapshot_json"] or "{}"),
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=_parse_dt(row["completed_at"]),
    )


async def list_meetings(*, limit: int = 20) -> list[MeetingRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute("SELECT * FROM meetings ORDER BY created_at DESC LIMIT ?", (limit,))
        ).fetchall()
    return [
        MeetingRecord(
            id=r["id"],
            title=r["title"],
            agenda=r["agenda"] or "",
            status=MeetingStatus(r["status"]),
            participants=json.loads(r["participants_json"] or "[]"),
            transcript_summary=r["transcript_summary"] or "",
            decisions=json.loads(r["decisions_json"] or "[]"),
            kpi_snapshot=json.loads(r["kpi_snapshot_json"] or "{}"),
            created_at=datetime.fromisoformat(r["created_at"]),
            completed_at=_parse_dt(r["completed_at"]),
        )
        for r in rows
    ]


async def save_meeting_item(item: MeetingItemRecord) -> MeetingItemRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO meeting_items
            (id, meeting_id, department_slug, head_role, report, blockers, plan)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.meeting_id,
                item.department_slug,
                item.head_role,
                item.report,
                item.blockers,
                item.plan,
            ),
        )
        await conn.commit()
    return item


async def list_meeting_items(meeting_id: str) -> list[MeetingItemRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                "SELECT * FROM meeting_items WHERE meeting_id = ? ORDER BY department_slug",
                (meeting_id,),
            )
        ).fetchall()
    return [
        MeetingItemRecord(
            id=r["id"],
            meeting_id=r["meeting_id"],
            department_slug=r["department_slug"],
            head_role=r["head_role"],
            report=r["report"] or "",
            blockers=r["blockers"] or "",
            plan=r["plan"] or "",
        )
        for r in rows
    ]


async def get_global_budget() -> BudgetRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (
            await conn.execute("SELECT * FROM office_budget WHERE id = 'budget-global'")
        ).fetchone()
    if not row:
        return BudgetRecord(id="budget-global", scope="global", limit_rub=50.0)
    return BudgetRecord(
        id=row["id"],
        scope=row["scope"],
        scope_id=row["scope_id"] or "",
        limit_rub=float(row["limit_rub"]),
        spent_rub=float(row["spent_rub"]),
        period=row["period"] or "day",
    )


async def add_budget_spend(amount: float, *, scope: str = "global", scope_id: str = "") -> float:
    if amount <= 0:
        budget = await get_global_budget()
        return budget.spent_rub
    async with aiosqlite.connect(_db_path()) as conn:
        if scope == "global":
            await conn.execute(
                "UPDATE office_budget SET spent_rub = spent_rub + ? WHERE id = 'budget-global'",
                (amount,),
            )
        else:
            row = await (
                await conn.execute(
                    "SELECT id FROM office_budget WHERE scope = ? AND scope_id = ?",
                    (scope, scope_id),
                )
            ).fetchone()
            if row:
                await conn.execute(
                    "UPDATE office_budget SET spent_rub = spent_rub + ? WHERE id = ?",
                    (amount, row[0]),
                )
            else:
                from uuid import uuid4

                await conn.execute(
                    """
                    INSERT INTO office_budget (id, scope, scope_id, limit_rub, spent_rub, period)
                    VALUES (?, ?, ?, ?, ?, 'day')
                    """,
                    (
                        str(uuid4()),
                        scope,
                        scope_id,
                        get_office_settings().office_dept_budget_rub,
                        amount,
                    ),
                )
        await conn.commit()
    budget = await get_global_budget()
    return budget.spent_rub


async def reset_daily_budget_if_needed() -> None:
    """Reset spent counters at day boundary (simple UTC day check via file marker)."""
    marker = OFFICE_ROOT / "data" / ".budget_day"
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
        return
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute("UPDATE office_budget SET spent_rub = 0")
        await conn.commit()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(today, encoding="utf-8")


def _online_event_from_row(r: aiosqlite.Row) -> OnlineEventRecord:
    return OnlineEventRecord(
        id=r["id"],
        title=r["title"],
        url=r["url"],
        event_type=r["event_type"] or "other",
        date_hint=r["date_hint"] or "",
        audience=r["audience"] or "",
        relevance=int(r["relevance"] or 5),
        why_relevant=r["why_relevant"] or "",
        registration_hint=r["registration_hint"] or "",
        source_brief=r["source_brief"] or "",
        status=r["status"] or "new",
        discovered_at=datetime.fromisoformat(r["discovered_at"]),
    )


async def save_online_event(ev: OnlineEventRecord) -> OnlineEventRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        existing = await (
            await conn.execute(
                "SELECT id FROM online_events WHERE url = ? LIMIT 1",
                (ev.url,),
            )
        ).fetchone()
        if existing:
            ev.id = existing["id"]
            await conn.execute(
                """
                UPDATE online_events
                SET title = ?, event_type = ?, date_hint = ?, audience = ?,
                    relevance = ?, why_relevant = ?, registration_hint = ?,
                    source_brief = ?, status = ?
                WHERE id = ?
                """,
                (
                    ev.title,
                    ev.event_type,
                    ev.date_hint,
                    ev.audience,
                    ev.relevance,
                    ev.why_relevant,
                    ev.registration_hint,
                    ev.source_brief,
                    ev.status,
                    ev.id,
                ),
            )
        else:
            await conn.execute(
                """
                INSERT INTO online_events
                (id, title, url, event_type, date_hint, audience, relevance,
                 why_relevant, registration_hint, source_brief, status, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev.id,
                    ev.title,
                    ev.url,
                    ev.event_type,
                    ev.date_hint,
                    ev.audience,
                    ev.relevance,
                    ev.why_relevant,
                    ev.registration_hint,
                    ev.source_brief,
                    ev.status,
                    ev.discovered_at.isoformat(),
                ),
            )
        await conn.commit()
    return ev


async def list_online_events(*, limit: int = 50, status: str | None = None) -> list[OnlineEventRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        if status:
            rows = await (
                await conn.execute(
                    """
                    SELECT * FROM online_events WHERE status = ?
                    ORDER BY relevance DESC, discovered_at DESC LIMIT ?
                    """,
                    (status, limit),
                )
            ).fetchall()
        else:
            rows = await (
                await conn.execute(
                    """
                    SELECT * FROM online_events
                    ORDER BY relevance DESC, discovered_at DESC LIMIT ?
                    """,
                    (limit,),
                )
            ).fetchall()
    return [_online_event_from_row(r) for r in rows]


async def update_online_event_status(event_id: str, status: str) -> OnlineEventRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "UPDATE online_events SET status = ? WHERE id = ?",
            (status, event_id),
        )
        await conn.commit()
    events = await list_online_events(limit=200)
    for ev in events:
        if ev.id == event_id:
            return ev
    return None


def _directive_from_row(r: aiosqlite.Row) -> DirectiveRecord:
    keys = r.keys()
    return DirectiveRecord(
        id=r["id"],
        brief=r["brief"],
        status=DirectiveStatus(r["status"]),
        coo_plan=r["coo_plan"] or "",
        schedule=json.loads(r["schedule_json"] or "[]") if "schedule_json" in keys else [],
        dept_results=json.loads(r["dept_results_json"] or "[]"),
        final_report=r["final_report"] or "",
        cost_rub=float(r["cost_rub"] or 0),
        created_at=datetime.fromisoformat(r["created_at"]),
        completed_at=_parse_dt(r["completed_at"]),
    )


async def save_directive(d: DirectiveRecord) -> DirectiveRecord:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO directives
            (id, brief, status, coo_plan, schedule_json, dept_results_json, final_report,
             cost_rub, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d.id,
                d.brief,
                d.status.value,
                d.coo_plan,
                json.dumps(d.schedule, ensure_ascii=False),
                json.dumps(d.dept_results, ensure_ascii=False),
                d.final_report,
                d.cost_rub,
                d.created_at.isoformat(),
                d.completed_at.isoformat() if d.completed_at else None,
            ),
        )
        await conn.commit()
    return d


async def update_directive(
    directive_id: str,
    *,
    status: DirectiveStatus | None = None,
    coo_plan: str | None = None,
    schedule: list | None = None,
    dept_results: list | None = None,
    final_report: str | None = None,
    cost_rub: float | None = None,
    completed_at: datetime | None = None,
) -> None:
    d = await get_directive(directive_id)
    if not d:
        return
    if status is not None:
        d.status = status
    if coo_plan is not None:
        d.coo_plan = coo_plan
    if schedule is not None:
        d.schedule = schedule
    if dept_results is not None:
        d.dept_results = dept_results
    if final_report is not None:
        d.final_report = final_report
    if cost_rub is not None:
        d.cost_rub = cost_rub
    if completed_at is not None:
        d.completed_at = completed_at
    await save_directive(d)


async def get_directive(directive_id: str) -> DirectiveRecord | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (
            await conn.execute("SELECT * FROM directives WHERE id = ?", (directive_id,))
        ).fetchone()
    return _directive_from_row(row) if row else None


async def list_directives(*, limit: int = 20) -> list[DirectiveRecord]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (
            await conn.execute(
                "SELECT * FROM directives ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        ).fetchall()
    return [_directive_from_row(r) for r in rows]
