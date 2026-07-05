from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class DealStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    MEETING = "meeting"
    WON = "won"
    LOST = "lost"


class DealRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    lead_id: str | None = None
    company_name: str = ""
    contact_email: str | None = None
    contact_phone: str | None = None
    status: DealStatus = DealStatus.NEW
    notes: str = ""
    proposal_json: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
