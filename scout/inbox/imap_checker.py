from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from email.header import decode_header

from scout.config import get_settings
from scout.notify.telegram import send_telegram
from scout.storage import db

logger = logging.getLogger(__name__)


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(chunk))
    return "".join(out)


def _extract_email_address(from_header: str) -> str | None:
    match = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", from_header)
    return match.group(0).lower() if match else None


def _check_inbox_sync(since_days: int = 14) -> list[dict]:
    settings = get_settings()
    if not settings.imap_host or not settings.imap_user:
        return []

    if settings.imap_use_ssl:
        mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    else:
        mail = imaplib.IMAP4(settings.imap_host, settings.imap_port)

    try:
        mail.login(settings.imap_user, settings.imap_password)
        mail.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        status, data = mail.search(None, f'(UNSEEN SINCE "{since}")')
        if status != "OK":
            return []

        replies: list[dict] = []
        for num in data[0].split():
            status, msg_data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            from_addr = _extract_email_address(_decode_header_value(msg.get("From")))
            subject = _decode_header_value(msg.get("Subject"))
            if not from_addr:
                continue
            replies.append(
                {
                    "from": from_addr,
                    "subject": subject[:120],
                    "date": _decode_header_value(msg.get("Date")),
                }
            )
        return replies
    finally:
        try:
            mail.logout()
        except Exception:
            pass


async def check_inbox_and_notify() -> list[dict]:
    """Проверяет непрочитанные ответы и шлёт в Telegram, если от известных лидов."""
    settings = get_settings()
    if not settings.imap_check_enabled:
        return []

    sent_contacts = await db.list_recent_sent_emails(days=21)
    if not sent_contacts:
        return []

    known = {row["email"].lower(): row for row in sent_contacts if row.get("email")}
    try:
        replies = await asyncio.to_thread(_check_inbox_sync)
    except Exception as exc:
        logger.warning("IMAP check failed: %s", exc)
        await send_telegram(f"⚠️ IMAP ошибка: {exc}")
        return []

    matched: list[dict] = []
    for reply in replies:
        addr = reply["from"]
        lead_info = known.get(addr)
        if not lead_info:
            continue
        matched.append({**reply, **lead_info})
        await send_telegram(
            "📩 Ответ от лида\n"
            f"{lead_info.get('company_name', '—')}\n"
            f"{addr}\n"
            f"Тема: {reply.get('subject') or '—'}"
        )

    if replies and not matched:
        logger.info("IMAP: %d unread, none from known leads", len(replies))

    return matched
