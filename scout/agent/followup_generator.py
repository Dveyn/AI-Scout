from __future__ import annotations

import json
import logging
from pathlib import Path

from scout.agent.skills.loader import load_skill
from scout.config import get_settings
from scout.llm.client import GPTunnelClient
from scout.models.schemas import AgentResult, FollowupMessage, LeadRecord, RawLead, Tone

logger = logging.getLogger(__name__)

FOLLOWUP_SKILL = "followup-writer"


async def generate_followups(
    lead: LeadRecord,
    *,
    product: str,
    tone: Tone,
    count: int | None = None,
) -> tuple[list[FollowupMessage], float]:
    """Генерирует касания 2–3 после первого письма."""
    settings = get_settings()
    if not lead.result or not lead.result.message or not lead.result.is_target:
        return [], 0.0

    n = count if count is not None else settings.followup_count
    n = max(1, min(2, n))

    skill = load_skill(FOLLOWUP_SKILL, include_examples=True)
    system = (
        "Ты пишешь follow-up письма для B2B cold outreach на русском. "
        "Каждое касание — новый угол, не «просто напоминаю». "
        "Верни ТОЛЬКО JSON-массив без markdown.\n\n"
        f"{skill}"
    )
    audit_hint = ""
    if lead.website_audit:
        issues = (lead.website_audit.get("issues") or [])[:3]
        if issues:
            audit_hint = "\nПроблемы сайта: " + "; ".join(issues)

    user = f"""Компания: {lead.raw.name}
Категория: {lead.raw.category or "—"}
Сайт: {lead.raw.website or "—"}
{audit_hint}

Продукт/оффер:
{product}

Тон: {tone.value}

Первое письмо (touch 1):
Subject: {lead.result.subject or "—"}
---
{lead.result.message}

Сгенерируй {n} follow-up (touch 2 и touch 3 если n=2).
Формат JSON:
[
  {{"touch": 2, "angle": "кратко угол", "subject": "тема или null для мессенджера", "message": "текст"}},
  {{"touch": 3, "angle": "breakup", "subject": "...", "message": "..."}}
]
"""

    client = GPTunnelClient()
    response = await client.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=None,
        tool_choice=None,
    )
    cost = response.cost_rub
    text = (response.content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Follow-up JSON parse failed for %s", lead.raw.name)
        return [], cost

    if not isinstance(data, list):
        return [], cost

    followups: list[FollowupMessage] = []
    for item in data[:n]:
        try:
            followups.append(FollowupMessage.model_validate(item))
        except Exception:
            continue
    return followups, cost
