from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DepartmentAgent(str, Enum):
    CMO = "cmo"
    SALES = "sales"
    SMM = "smm"
    ADS = "ads"
    SEO = "seo"
    ANALYTICS = "analytics"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PENDING_CMO_APPROVAL = "pending_cmo_approval"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    REJECTED = "rejected"
    FAILED = "failed"


class ContentStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


class AdCreativeStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class DepartmentTaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent: DepartmentAgent
    task_type: str
    priority: int = Field(default=5, ge=1, le=10)
    status: TaskStatus = TaskStatus.PENDING
    brief: str = ""
    input_json: dict[str, Any] = Field(default_factory=dict)
    output_json: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


class AgentLogRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent: DepartmentAgent
    action: str
    input_preview: str = ""
    output_preview: str = ""
    cost_rub: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentPostRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str | None = None
    platform: str
    title: str = ""
    body: str
    status: ContentStatus = ContentStatus.DRAFT
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AdCreativeRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str | None = None
    headlines: list[str] = Field(default_factory=list)
    body: str = ""
    audience: str = ""
    ab_hypothesis: str = ""
    status: AdCreativeStatus = AdCreativeStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
