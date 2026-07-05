from __future__ import annotations

import logging
import re

import httpx

from scout.config import get_settings
from scout.models.schemas import RawLead
from scout.storage.company_dedup import company_keys, matches_scanned

logger = logging.getLogger(__name__)

TWOGIS_ITEMS_URL = "https://catalog.api.2gis.com/3.0/items"


class TwogisCollector:
    """Официальный 2GIS Places API — без скрейпинга."""

    async def collect(
        self,
        query: str,
        city: str,
        limit: int,
        *,
        exclude_keys: set[str] | None = None,
    ) -> list[RawLead]:
        settings = get_settings()
        api_key = settings.twogis_api_key
        if not api_key:
            raise ValueError("TWOGIS_API_KEY не задан в scout/.env")

        search_text = f"{query} {city}".strip()
        known = exclude_keys or set()
        leads: list[RawLead] = []
        page = 1
        page_size = min(max(limit, 1), 50)

        async with httpx.AsyncClient(timeout=45.0) as client:
            while len(leads) < limit:
                params = {
                    "q": search_text,
                    "type": "branch",
                    "page": page,
                    "page_size": page_size,
                    "key": api_key,
                    "fields": "items.contact_groups,items.reviews,items.rubrics",
                }
                resp = await client.get(TWOGIS_ITEMS_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
                items = (payload.get("result") or {}).get("items") or []
                if not items:
                    break

                for item in items:
                    lead = _item_to_lead(item)
                    if matches_scanned(lead, known):
                        continue
                    for key in company_keys(lead):
                        known.add(key)
                    leads.append(lead)
                    if len(leads) >= limit:
                        break

                meta = (payload.get("result") or {}).get("meta") or {}
                total_pages = int(meta.get("page_count") or 1)
                if page >= total_pages:
                    break
                page += 1

        logger.info("2GIS collected %d leads for %s", len(leads), search_text)
        return leads[:limit]


def _item_to_lead(item: dict) -> RawLead:
    name = str(item.get("name") or item.get("name_ex", {}).get("primary") or "Без названия")
    address = item.get("address_name") or item.get("full_name")
    phone = email = website = None

    for group in item.get("contact_groups") or []:
        for contact in group.get("contacts") or []:
            ctype = (contact.get("type") or "").lower()
            value = contact.get("value") or contact.get("text")
            if not value:
                continue
            if ctype == "phone" and not phone:
                phone = str(value)
            elif ctype == "email" and not email:
                email = str(value)
            elif ctype in ("website", "url") and not website:
                website = str(value)

    reviews = item.get("reviews") or {}
    rating = reviews.get("rating")
    reviews_count = reviews.get("count") or reviews.get("review_count")

    rubrics = item.get("rubrics") or []
    category = ", ".join(r.get("name", "") for r in rubrics[:2] if r.get("name")) or None

    firm_id = item.get("id") or item.get("org", {}).get("id")
    maps_url = f"https://2gis.com/firm/{firm_id}" if firm_id else None

    return RawLead(
        name=name.strip(),
        category=category,
        address=str(address) if address else None,
        phone=phone,
        email=email,
        website=website,
        rating=float(rating) if rating is not None else None,
        reviews_count=int(reviews_count) if reviews_count is not None else None,
        maps_url=maps_url,
        snippet=category,
        source="2gis",
    )


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        return "+7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    return raw
