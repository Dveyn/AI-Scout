from __future__ import annotations

import re
from urllib.parse import urlparse

from scout.models.schemas import RawLead
from scout.outreach.dedup import normalize_phone

ORG_SLUG_RE = re.compile(r"/org/([^/]+)/\d+", re.I)
GENERIC_BRAND_NAMES = frozenset(
    {
        "суши",
        "пицца",
        "доставка",
        "ресторан",
        "кафе",
        "бар",
        "бургерная",
        "пиццерия",
        "суши-бар",
        "столовая",
        "кофейня",
    }
)
NON_BRAND_WEB_HOSTS = frozenset(
    {
        "yandex.ru",
        "2gis.ru",
        "google.com",
        "goo.gl",
        "linktr.ee",
        "taplink.cc",
        "t.me",
        "vk.com",
        "instagram.com",
        "facebook.com",
        "ok.ru",
    }
)


def maps_brand_slug(maps_url: str | None) -> str | None:
    """Yandex Maps chain slug — often shared across branches."""
    if not maps_url:
        return None
    match = ORG_SLUG_RE.search(maps_url)
    if not match:
        return None
    slug = match.group(1).strip().lower()
    return slug or None


def website_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or host in NON_BRAND_WEB_HOSTS:
        return None
    return host


def brand_name_key(name: str) -> str | None:
    """Normalize listing title to brand (drop branch/address suffixes)."""
    brand = name.strip().lower()
    brand = re.sub(r",.*$", "", brand)
    brand = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", brand)
    brand = re.sub(r"\s*[\—\-–].*$", "", brand)
    brand = re.sub(r"\s+", " ", brand).strip()
    if len(brand) < 4 or brand in GENERIC_BRAND_NAMES:
        return None
    return brand


def company_keys(lead: RawLead) -> list[str]:
    """All aliases for the same organization (brand / network)."""
    keys: list[str] = []

    domain = website_domain(lead.website)
    if domain:
        keys.append(f"web:{domain}")

    slug = maps_brand_slug(lead.maps_url)
    if slug:
        keys.append(f"brand:{slug}")

    phone = normalize_phone(lead.phone)
    if phone:
        keys.append(f"phone:{phone}")

    brand = brand_name_key(lead.name)
    if brand:
        keys.append(f"name:{brand}")

    if not keys:
        keys.append(f"name:{re.sub(r'\s+', ' ', lead.name.strip().lower())}")

    return list(dict.fromkeys(keys))


def company_key(lead: RawLead) -> str:
    """Primary dedup key (first alias)."""
    return company_keys(lead)[0]


def matches_scanned(lead: RawLead, scanned: set[str]) -> bool:
    return any(key in scanned for key in company_keys(lead))
