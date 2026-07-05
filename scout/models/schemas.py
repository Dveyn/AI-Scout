from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from scout.models.contacts import LeadContacts, OutreachChannel


class JobStatus(str, Enum):
    PENDING = "pending"
    COLLECTING = "collecting"
    SCOUTING = "scouting"
    DONE = "done"
    FAILED = "failed"


class Tone(str, Enum):
    BUSINESS = "business"
    FRIENDLY = "friendly"


class SendStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    NO_EMAIL = "no_email"
    READY = "ready"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


class RawLead(BaseModel):
    name: str
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    rating: float | None = None
    reviews_count: int | None = None
    maps_url: str | None = None
    snippet: str | None = None
    source: str | None = None  # yandex | 2gis
    inn: str | None = None
    annual_revenue_rub: float | None = None
    revenue_year: int | None = None


class AgentResult(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    is_target: bool
    reason: str
    pains: list[str] = Field(default_factory=list, max_length=3)
    hook: str = ""
    product_angle: str = ""
    subject: str | None = None
    message: str | None = None
    channel_hint: str = "phone"
    reasoning_summary: str = ""
    website_issues: list[str] = Field(default_factory=list, max_length=5)
    lpr_name: str | None = None


class FollowupMessage(BaseModel):
    touch: int = Field(ge=2, le=3)
    angle: str = ""
    subject: str | None = None
    message: str
    send_status: SendStatus = SendStatus.PENDING
    sent_at: datetime | None = None


class AgentTraceStep(BaseModel):
    round: int
    type: str
    content: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result_preview: str | None = None


class ProcessedLead(BaseModel):
    raw: RawLead
    result: AgentResult
    trace: list[AgentTraceStep] = Field(default_factory=list)
    llm_cost_rub: float = 0.0


class ICPConfig(BaseModel):
    icp: str
    product: str
    offer: str | None = None
    query: str
    city: str
    limit: int = Field(default=10, ge=1, le=200)
    tone: Tone = Tone.BUSINESS
    auto_send: bool = False
    agent_skill: str | None = None
    preset: str | None = None
    generate_followups: bool = True


class JobCreate(BaseModel):
    icp: str = "Локальный B2B с сайтом"
    product: str = "Услуги digital-маркетинга"
    offer: str | None = None
    query: str
    city: str
    limit: int = Field(default=10, ge=1, le=200)
    tone: Tone = Tone.BUSINESS
    auto_send: bool = False
    agent_skill: str | None = None
    preset: str | None = None
    generate_followups: bool = True


class JobReport(BaseModel):
    job_id: str
    collected: int = 0
    email_found: int = 0
    targets: int = 0
    sent: int = 0
    ready_manual: int = 0
    no_contact: int = 0
    no_email: int = 0
    duplicate: int = 0
    failed: int = 0
    skipped: int = 0


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    icp: str
    product: str
    offer: str | None = None
    query: str
    city: str
    limit: int
    tone: Tone
    auto_send: bool = False
    agent_skill: str | None = None
    preset: str | None = None
    generate_followups: bool = True
    status: JobStatus = JobStatus.PENDING
    progress_current: int = 0
    progress_total: int = 0
    llm_cost_rub: float = 0.0
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LeadRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    raw: RawLead
    result: AgentResult | None = None
    trace: list[AgentTraceStep] = Field(default_factory=list)
    website_audit: dict | None = None
    email: str | None = None
    fit_score: int | None = None
    llm_cost_rub: float = 0.0
    send_status: SendStatus | None = None
    send_error: str | None = None
    sent_at: datetime | None = None
    fallback_text: str | None = None
    contacts: LeadContacts | None = None
    outreach_channels: list[OutreachChannel] = Field(default_factory=list)
    followups: list[FollowupMessage] = Field(default_factory=list)
    sequence_touch_sent: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OutreachLogEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    lead_id: str
    company_name: str
    email: str | None = None
    phone: str | None = None
    channel: str
    subject: str | None = None
    message_preview: str | None = None
    touch_number: int = 1
    status: SendStatus
    error: str | None = None
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class DashboardStats(BaseModel):
    total_jobs: int = 0
    total_leads: int = 0
    total_targets: int = 0
    emails_found: int = 0
    emails_sent: int = 0
    no_email: int = 0
    failed: int = 0
    duplicates: int = 0
    total_llm_cost_rub: float = 0.0
