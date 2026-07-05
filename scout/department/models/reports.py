from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class KpiSnapshot(BaseModel):
    leads: int = 0
    targets: int = 0
    emails_sent: int = 0
    deals_new: int = 0
    deals_won: int = 0
    conversion_rate: float = 0.0
    cpl: float = 0.0
    cac: float = 0.0
    romi: float = 0.0
    llm_cost_rub: float = 0.0
    ad_spend_rub: float = 0.0
    revenue_rub: float = 0.0


class DailyReportRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    report_date: str
    kpi: KpiSnapshot = Field(default_factory=KpiSnapshot)
    recommendations: list[str] = Field(default_factory=list)
    summary: str = ""
    raw_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
