from __future__ import annotations

import re
from urllib.parse import quote

from scout.models.contacts import LeadContacts, OutreachChannel


def messenger_text(message: str, *, lpr_name: str | None = None) -> str:
    text = message.strip()
    if lpr_name and not text.lower().startswith(lpr_name.split()[0].lower()):
        text = f"{lpr_name}, добрый день!\n\n{text}"
    if len(text) > 900:
        text = text[:897].rstrip() + "…"
    return text


def build_outreach_channels(
    contacts: LeadContacts,
    message: str,
    *,
    subject: str | None = None,
    email: str | None = None,
) -> list[OutreachChannel]:
    text = messenger_text(message, lpr_name=contacts.lpr_name)
    channels: list[OutreachChannel] = []

    primary_email = email or (contacts.emails[0] if contacts.emails else None)
    if primary_email:
        channels.append(
            OutreachChannel(
                channel="email",
                label=f"Email: {primary_email}",
                url=f"mailto:{primary_email}?subject={quote(subject or 'Сотрудничество')}&body={quote(text)}",
                contact_value=primary_email,
                message=text,
                auto=True,
            )
        )

    for username in contacts.telegram[:3]:
        user = username.lstrip("@")
        channels.append(
            OutreachChannel(
                channel="telegram",
                label=f"Telegram: @{user}",
                url=f"https://t.me/{user}",
                contact_value=f"@{user}",
                message=text,
            )
        )

    for vk_url in contacts.vk[:3]:
        slug = vk_url.rstrip("/").split("/")[-1]
        write_url = vk_url
        if slug.lstrip("-").isdigit() or slug.startswith("club") or slug.startswith("public"):
            gid = _vk_write_id(slug)
            if gid:
                write_url = f"https://vk.com/write{gid}"
        channels.append(
            OutreachChannel(
                channel="vk",
                label=f"VK: {slug}",
                url=write_url,
                contact_value=vk_url,
                message=text,
            )
        )

    for max_url in contacts.max_links[:2]:
        channels.append(
            OutreachChannel(
                channel="max",
                label="Max",
                url=max_url,
                contact_value=max_url,
                message=text,
            )
        )

    for wa_url in contacts.whatsapp[:2]:
        channels.append(
            OutreachChannel(
                channel="whatsapp",
                label="WhatsApp",
                url=wa_url if "?" in wa_url else f"{wa_url}?text={quote(text)}",
                contact_value=wa_url,
                message=text,
            )
        )

    for phone in contacts.phones[:2]:
        digits = "".join(c for c in phone if c.isdigit())
        channels.append(
            OutreachChannel(
                channel="phone",
                label=f"Телефон: {phone}",
                url=f"tel:{digits}",
                contact_value=phone,
                message=text,
            )
        )
        if not any(c.channel == "whatsapp" for c in channels):
            channels.append(
                OutreachChannel(
                    channel="whatsapp",
                    label=f"WhatsApp: {phone}",
                    url=f"https://wa.me/{digits}?text={quote(text)}",
                    contact_value=phone,
                    message=text,
                )
            )

    return _dedupe_channels(channels)


def _vk_write_id(slug: str) -> str | None:
    digits = re.sub(r"\D", "", slug)
    if not digits:
        return None
    if slug.startswith("club") or slug.startswith("public"):
        return f"-{digits}"
    return digits


def _dedupe_channels(channels: list[OutreachChannel]) -> list[OutreachChannel]:
    seen: set[tuple[str, str]] = set()
    out: list[OutreachChannel] = []
    for ch in channels:
        key = (ch.channel, ch.contact_value.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(ch)
    return out


def best_manual_channel(channels: list[OutreachChannel]) -> OutreachChannel | None:
    priority = ("telegram", "vk", "max", "whatsapp", "phone")
    for name in priority:
        for ch in channels:
            if ch.channel == name:
                return ch
    return None
