from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from scout.config import get_settings
from scout.models.schemas import RawLead

logger = logging.getLogger(__name__)

DADATA_PARTY_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"


@dataclass
class RevenueLookup:
    inn: str | None = None
    annual_revenue_rub: float | None = None
    revenue_year: int | None = None
    company_name: str | None = None
    below_threshold: bool = False
    skip_reason: str | None = None


async def lookup_revenue(lead: RawLead, city: str) -> RevenueLookup:
    """Поиск выручки компании через DaData (finance.revenue — ₽/год)."""
    settings = get_settings()
    if not settings.dadata_api_key:
        return RevenueLookup()

    query = f"{lead.name} {city}".strip()
    headers = {
        "Authorization": f"Token {settings.dadata_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                DADATA_PARTY_URL,
                headers=headers,
                json={"query": query, "count": 3},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("DaData lookup failed for %s: %s", lead.name, exc)
        if settings.revenue_filter_strict:
            return RevenueLookup(skip_reason="Нет ответа DaData — фильтр strict")
        return RevenueLookup()

    suggestions = data.get("suggestions") or []
    if not suggestions:
        if settings.revenue_filter_strict:
            return RevenueLookup(skip_reason="Компания не найдена в DaData")
        return RevenueLookup()

    best = suggestions[0]
    party = best.get("data") or {}
    finance = party.get("finance") or {}
    revenue = finance.get("revenue")
    year = finance.get("year")
    inn = party.get("inn")
    legal_name = party.get("name", {}).get("short_with_opf") or best.get("value")

    result = RevenueLookup(
        inn=str(inn) if inn else None,
        annual_revenue_rub=float(revenue) if revenue is not None else None,
        revenue_year=int(year) if year else None,
        company_name=legal_name,
    )

    min_annual = settings.icp_min_monthly_revenue_rub * 12
    if result.annual_revenue_rub is not None and result.annual_revenue_rub < min_annual:
        monthly = result.annual_revenue_rub / 12
        result.below_threshold = True
        result.skip_reason = (
            f"Выручка ~{monthly:,.0f} ₽/мес по DaData "
            f"(порог {settings.icp_min_monthly_revenue_rub:,.0f} ₽/мес)"
        ).replace(",", " ")
    elif result.annual_revenue_rub is None and settings.revenue_filter_strict:
        result.skip_reason = "Нет данных о выручке в DaData"

    return result


async def apply_revenue_to_lead(lead: RawLead, city: str) -> str | None:
    """Обогащает лид и возвращает причину skip или None."""
    settings = get_settings()
    if not settings.revenue_filter_enabled:
        return None

    lookup = await lookup_revenue(lead, city)
    lead.inn = lookup.inn
    lead.annual_revenue_rub = lookup.annual_revenue_rub
    lead.revenue_year = lookup.revenue_year

    if lookup.below_threshold or lookup.skip_reason:
        return lookup.skip_reason
    return None
