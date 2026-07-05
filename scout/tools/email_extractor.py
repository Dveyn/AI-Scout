from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

TIMEOUT = 10.0
USER_AGENT = "Mozilla/5.0 (compatible; AIScout/1.0)"

# Common false positives on Russian business sites
SKIP_EMAIL_SUFFIXES = (
    "@example.com",
    "@domain.com",
    "@email.com",
    "@yandex.ru/maps",
    "@sentry.io",
    "@wixpress.com",
)

CONTACT_PATHS = (
    "/contacts",
    "/contact",
    "/kontakty",
    "/kontakt",
    "/about",
    "/o-nas",
    "/o-kompanii",
    "/svyaz",
)

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

MAILTO_PATTERN = re.compile(
    r'href=["\']mailto:([^"\'?>\s]+)',
    re.IGNORECASE,
)

PREFERRED_PREFIXES = ("info", "contact", "mail", "office", "sales", "hello", "admin")


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _is_valid_email(email: str) -> bool:
    email = email.strip().lower()
    if len(email) < 6 or len(email) > 80:
        return False
    if any(email.endswith(suffix) for suffix in SKIP_EMAIL_SUFFIXES):
        return False
    if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False
    return True


def _extract_from_html(html: str) -> list[str]:
    found: list[str] = []
    for match in MAILTO_PATTERN.findall(html):
        email = match.strip().lower()
        if _is_valid_email(email):
            found.append(email)
    for match in EMAIL_PATTERN.findall(html):
        email = match.strip().lower()
        if _is_valid_email(email):
            found.append(email)
    return found


def _rank_email(email: str) -> tuple[int, str]:
    local = email.split("@", 1)[0].lower()
    for idx, prefix in enumerate(PREFERRED_PREFIXES):
        if local == prefix or local.startswith(prefix):
            return (idx, email)
    return (len(PREFERRED_PREFIXES), email)


def pick_best_email(emails: list[str]) -> str | None:
    unique = list(dict.fromkeys(e.lower() for e in emails if _is_valid_email(e)))
    if not unique:
        return None
    return sorted(unique, key=_rank_email)[0]


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except Exception:
        return None


async def extract_emails_from_website(url: str) -> list[str]:
    """Crawl homepage and common contact pages for email addresses."""
    if not url:
        return []

    base_url = _normalize_url(url)
    collected: list[str] = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        html = await _fetch_html(client, base_url)
        if html:
            collected.extend(_extract_from_html(html))

        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        for path in CONTACT_PATHS:
            page_url = urljoin(origin + "/", path.lstrip("/"))
            page_html = await _fetch_html(client, page_url)
            if page_html:
                collected.extend(_extract_from_html(page_html))

    return list(dict.fromkeys(collected))


async def find_best_email(url: str | None) -> str | None:
    emails = await extract_emails_from_website(url or "")
    return pick_best_email(emails)
