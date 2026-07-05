from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    DONE = "done"


class GoalHorizon(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class GoalStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


class DirectiveStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_CURSOR = "waiting_cursor"
    COMPLETED = "completed"
    FAILED = "failed"


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ModelTier(str, Enum):
    STRATEGY = "strategy"
    EXECUTION = "execution"


class DepartmentRecord(BaseModel):
    id: str
    name: str
    slug: str
    head_role: str = ""
    description: str = ""


class WorkstationRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    preset_id: str = ""
    department_slug: str
    role: str
    model_tier: ModelTier = ModelTier.EXECUTION
    custom_prompt: str = ""
    skills: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    current_task: str = ""
    last_result: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ActivityRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workstation_id: str
    step: str
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OnlineEventRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    url: str
    event_type: str = "other"
    date_hint: str = ""
    audience: str = ""
    relevance: int = 5
    why_relevant: str = ""
    registration_hint: str = ""
    source_brief: str = ""
    status: str = "new"
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


class GoalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    horizon: GoalHorizon
    text: str
    status: GoalStatus = GoalStatus.ACTIVE
    owner_department: str = ""
    parent_goal_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class MeetingRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = "Standup"
    agenda: str = ""
    status: MeetingStatus = MeetingStatus.SCHEDULED
    participants: list[str] = Field(default_factory=list)
    transcript_summary: str = ""
    decisions: list[str] = Field(default_factory=list)
    kpi_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class MeetingItemRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    meeting_id: str
    department_slug: str
    head_role: str
    report: str = ""
    blockers: str = ""
    plan: str = ""


class BudgetRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    scope: str  # global | department | agent
    scope_id: str = ""
    limit_rub: float = 0.0
    spent_rub: float = 0.0
    period: str = "day"


class PresetDefinition(BaseModel):
    id: str
    role: str
    department: str
    model_tier: ModelTier = ModelTier.EXECUTION
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    backstory: str = ""
    is_head: bool = False


class OfficeOverview(BaseModel):
    departments: list[DepartmentRecord]
    workstations: list[WorkstationRecord]
    goals: list[GoalRecord]
    active_meetings: list[MeetingRecord]
    budget_global: BudgetRecord | None = None
    scout_stats: dict[str, Any] = Field(default_factory=dict)
    department_stats: dict[str, Any] = Field(default_factory=dict)


class DirectiveRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    brief: str
    status: DirectiveStatus = DirectiveStatus.PLANNING
    coo_plan: str = ""
    schedule: list[dict[str, Any]] = Field(default_factory=list)
    dept_results: list[dict[str, Any]] = Field(default_factory=list)
    final_report: str = ""
    cost_rub: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class GoalCascadeResult(BaseModel):
    parent_goal: GoalRecord
    child_goals: list[GoalRecord]
    department_tasks: list[dict[str, Any]] = Field(default_factory=list)
    cost_rub: float = 0.0
    summary: str = ""


class StandupResult(BaseModel):
    meeting: MeetingRecord
    items: list[MeetingItemRecord]
    coo_synthesis: str = ""
    day_plan: list[str] = Field(default_factory=list)
    cost_rub: float = 0.0
