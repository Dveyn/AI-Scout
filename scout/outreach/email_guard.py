from __future__ import annotations

import re

BLOCKED_LOCALS = (
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "postmaster",
    "mailer-daemon",
    "abuse",
    "spam",
    "bounce",
    "newsletter",
    "unsubscribe",
    "robot",
    "support-noreply",
)

BLOCKED_DOMAINS = (
    "example.com",
    "test.com",
    "wixpress.com",
    "sentry.io",
)

ROLE_OK_FOR_B2B = ("info", "contact", "mail", "office", "sales", "hello", "admin", "zakaz", "order")


def is_sendable_email(email: str | None) -> tuple[bool, str | None]:
    if not email:
        return False, "Нет email"
    email = email.strip().lower()
    if not re.match(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", email):
        return False, "Некорректный формат"

    local, _, domain = email.partition("@")
    if any(domain == d or domain.endswith("." + d) for d in BLOCKED_DOMAINS):
        return False, f"Заблокированный домен: {domain}"
    if any(local.startswith(p) or local == p for p in BLOCKED_LOCALS):
        return False, f"Технический ящик: {local}"

    # Слишком длинный local — часто автогенерация
    if len(local) > 40:
        return False, "Подозрительно длинный local-part"

    return True, None


def email_quality_score(email: str) -> int:
    """Выше = лучше для cold outreach."""
    local = email.split("@", 1)[0].lower()
    for idx, prefix in enumerate(ROLE_OK_FOR_B2B):
        if local == prefix or local.startswith(prefix):
            return 100 - idx * 5
    if "." in local or local.isdigit():
        return 40
    return 60
