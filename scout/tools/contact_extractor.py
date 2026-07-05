from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from scout.models.contacts import LeadContacts
from scout.tools.email_extractor import EMAIL_PATTERN, _is_valid_email, pick_best_email

TIMEOUT = 10.0
USER_AGENT = "Mozilla/5.0 (compatible; AIScout/1.0)"

CONTACT_PATHS = (
    "/contacts",
    "/contact",
    "/kontakty",
    "/kontakt",
    "/about",
    "/o-nas",
    "/o-kompanii",
    "/team",
    "/komanda",
)

TELEGRAM_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{4,32})",
    re.IGNORECASE,
)
TELEGRAM_AT_RE = re.compile(r"@([a-zA-Z][a-zA-Z0-9_]{3,31})")
VK_RE = re.compile(
    r"https?://(?:www\.)?vk\.com/(?!share)([a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)
MAX_RE = re.compile(
    r"https?://(?:www\.)?(?:max\.ru|web\.max\.ru)/[^\s\"'<>]+",
    re.IGNORECASE,
)
WHATSAPP_RE = re.compile(
    r"https?://(?:wa\.me|api\.whatsapp\.com)/[^\s\"'<>]+",
    re.IGNORECASE,
)
TEL_RE = re.compile(r'href=["\']tel:([^"\']+)["\']', re.IGNORECASE)
PHONE_TEXT_RE = re.compile(
    r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)

LPR_PATTERNS = [
    (
        r"(?:генеральный\s+директор|директор|руководитель|владелец|управляющий)"
        r"[:\s\-–—]+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})",
        "руководитель",
    ),
    (
        r"([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)"
        r"\s*[,—\-–]\s*(?:генеральный\s+директор|директор|руководитель)",
        "руководитель",
    ),
]

SKIP_TELEGRAM = {"share", "joinchat", "addstickers", "iv", "proxy", "socks"}


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _normalize_phone(phone: str) -> str | None:
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return None
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return f"+{digits}" if not phone.strip().startswith("+") else f"+{digits}"


def _extract_from_html(html: str, source: str) -> LeadContacts:
    contacts = LeadContacts(source_notes=[source])
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)

    for email in EMAIL_PATTERN.findall(html):
        if _is_valid_email(email):
            contacts.emails.append(email.lower())

    for match in TEL_RE.findall(html):
        phone = _normalize_phone(match)
        if phone:
            contacts.phones.append(phone)

    for match in PHONE_TEXT_RE.findall(text):
        phone = _normalize_phone(match)
        if phone and phone not in contacts.phones:
            contacts.phones.append(phone)

    for match in TELEGRAM_RE.findall(html):
        user = match.strip().lstrip("@")
        if user.lower() not in SKIP_TELEGRAM:
            contacts.telegram.append(user)

    for match in TELEGRAM_AT_RE.findall(text):
        if match.lower() not in SKIP_TELEGRAM and len(match) > 3:
            contacts.telegram.append(match)

    for match in VK_RE.findall(html):
        slug = match.strip("/")
        if slug and slug not in ("id", "club", "public"):
            contacts.vk.append(f"https://vk.com/{slug}")

    for match in MAX_RE.findall(html):
        contacts.max_links.append(match.rstrip(".,;)"))

    for match in WHATSAPP_RE.findall(html):
        contacts.whatsapp.append(match.rstrip(".,;)"))

    for pattern, role in LPR_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            name = m.group(1).strip()
            if 5 < len(name) < 60:
                contacts.lpr_name = name
                contacts.lpr_role = role
                break

    return contacts


def pick_best_channel(contacts: LeadContacts) -> str | None:
    if contacts.emails:
        return "email"
    if contacts.telegram:
        return "telegram"
    if contacts.vk:
        return "vk"
    if contacts.max_links:
        return "max"
    if contacts.whatsapp:
        return "whatsapp"
    if contacts.phones:
        return "phone"
    return None


def finalize_contacts(contacts: LeadContacts) -> LeadContacts:
    contacts.emails = list(dict.fromkeys(contacts.emails))
    contacts.phones = list(dict.fromkeys(contacts.phones))
    contacts.telegram = list(dict.fromkeys(contacts.telegram))
    contacts.vk = list(dict.fromkeys(contacts.vk))
    contacts.max_links = list(dict.fromkeys(contacts.max_links))
    contacts.whatsapp = list(dict.fromkeys(contacts.whatsapp))
    contacts.best_channel = pick_best_channel(contacts)
    return contacts


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except Exception:
        return None


async def extract_contacts_from_website(url: str | None) -> LeadContacts:
    if not url:
        return LeadContacts()

    base_url = _normalize_url(url)
    merged = LeadContacts()

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        html = await _fetch_html(client, base_url)
        if html:
            merged = merged.merge(_extract_from_html(html, "сайт: главная"))

        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        for path in CONTACT_PATHS:
            page_url = urljoin(origin + "/", path.lstrip("/"))
            page_html = await _fetch_html(client, page_url)
            if page_html:
                merged = merged.merge(_extract_from_html(page_html, f"сайт: {path}"))

    return finalize_contacts(merged)


def contacts_from_maps_data(
    *,
    emails: list[str],
    phones: list[str],
    links: list[str],
    body_text: str = "",
) -> LeadContacts:
    merged = LeadContacts(source_notes=["яндекс.карты"])
    for email in emails:
        if _is_valid_email(email):
            merged.emails.append(email.lower())
    for phone in phones:
        normalized = _normalize_phone(phone)
        if normalized:
            merged.phones.append(normalized)

    blob = "\n".join(links) + "\n" + body_text
    merged = merged.merge(_extract_from_html(blob, "яндекс.карты: ссылки"))

    for link in links:
        lower = link.lower()
        if "t.me/" in lower or "telegram.me/" in lower:
            m = TELEGRAM_RE.search(link)
            if m:
                merged.telegram.append(m.group(1))
        elif "vk.com/" in lower:
            merged.vk.append(link.split("?")[0])
        elif "max.ru" in lower or "web.max.ru" in lower:
            merged.max_links.append(link.split("?")[0])
        elif "wa.me" in lower or "whatsapp.com" in lower:
            merged.whatsapp.append(link)

    return finalize_contacts(merged)
