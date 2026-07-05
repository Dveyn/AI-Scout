from __future__ import annotations

import json
import logging
from datetime import datetime

from scout.department.base_agent import BaseAgent
from scout.department.models import DealRecord, DealStatus
from scout.storage import department_db as db

logger = logging.getLogger(__name__)


class SalesAgent(BaseAgent):
    agent_name = "sales"

    async def create_deal_from_lead(
        self,
        lead_id: str,
        company_name: str,
        email: str | None,
        phone: str | None,
    ) -> DealRecord:
        existing = await db.list_deals(limit=500)
        for d in existing:
            if d.lead_id == lead_id:
                return d
        deal = DealRecord(
            lead_id=lead_id,
            company_name=company_name,
            contact_email=email,
            contact_phone=phone,
            status=DealStatus.NEW,
        )
        return await db.create_deal(deal)

    async def handle_inbox_reply(self, reply: dict) -> dict:
        """Generate reply draft for an inbound email."""
        company = reply.get("company_name", "")
        subject = reply.get("subject", "")
        from_addr = reply.get("from", "")
        lead_id = reply.get("lead_id")

        deal = None
        if lead_id:
            deals = await db.list_deals(limit=200)
            deal = next((d for d in deals if d.lead_id == lead_id), None)
            if not deal:
                deal = await self.create_deal_from_lead(
                    lead_id, company, from_addr, reply.get("phone")
                )

        prompt = (
            f"Входящий ответ от лида.\n"
            f"Компания: {company}\n"
            f"Email: {from_addr}\n"
            f"Тема: {subject}\n\n"
            f"Сгенерируй ответ для продолжения диалога и доведения до созвона."
        )
        result, summary, _ = await self.run(prompt, action="inbox_reply")
        if deal and result:
            await db.update_deal_status(deal.id, DealStatus.IN_PROGRESS, notes=summary[:500])
        return result

    async def generate_proposal(self, deal_id: str) -> dict:
        deal = await db.get_deal(deal_id)
        if not deal:
            return {}
        prompt = (
            f"Подготовь коммерческое предложение для:\n"
            f"Компания: {deal.company_name}\n"
            f"Email: {deal.contact_email}\n"
            f"Статус: {deal.status.value}\n"
            f"Заметки: {deal.notes}"
        )
        result, summary, _ = await self.run(prompt, action="generate_proposal")
        if result:
            await db.update_deal_proposal(deal_id, json.dumps(result, ensure_ascii=False))
        return result
