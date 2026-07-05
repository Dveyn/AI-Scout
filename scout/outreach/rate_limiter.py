from __future__ import annotations

import asyncio
import logging
import random

from scout.config import get_settings
from scout.runtime.daily_state import (
    domain_sent_today,
    emails_sent_this_hour,
    emails_sent_today,
    record_email_sent,
)

logger = logging.getLogger(__name__)


def can_send_email(email: str) -> tuple[bool, str | None]:
    settings = get_settings()
    if settings.max_emails_per_day > 0 and emails_sent_today() >= settings.max_emails_per_day:
        return False, f"Дневной лимит отправок ({settings.max_emails_per_day})"

    if settings.max_emails_per_hour > 0 and emails_sent_this_hour() >= settings.max_emails_per_hour:
        return False, f"Часовой лимит отправок ({settings.max_emails_per_hour})"

    domain = email.split("@", 1)[-1].lower() if "@" in email else ""
    if settings.max_emails_per_domain_per_day > 0 and domain:
        if domain_sent_today(domain) >= settings.max_emails_per_domain_per_day:
            return False, f"Лимит на домен {domain} ({settings.max_emails_per_domain_per_day}/день)"

    return True, None


async def wait_before_send() -> None:
    settings = get_settings()
    lo = settings.send_delay_sec_min
    hi = max(lo, settings.send_delay_sec_max)
    if hi <= 0:
        return
    delay = random.uniform(lo, hi)
    logger.info("Anti-spam delay: %.0f sec", delay)
    await asyncio.sleep(delay)


def mark_sent(email: str) -> None:
    record_email_sent(email)
