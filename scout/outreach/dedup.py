from __future__ import annotations

import hashlib
import re


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return None
    return digits[-10:]


def contact_key(
    email: str | None,
    phone: str | None,
    *,
    telegram: str | None = None,
    vk: str | None = None,
) -> str | None:
    if email:
        return f"email:{email.strip().lower()}"
    if telegram:
        return f"telegram:{telegram.strip().lstrip('@').lower()}"
    if vk:
        return f"vk:{vk.strip().lower()}"
    normalized = normalize_phone(phone)
    if normalized:
        return f"phone:{normalized}"
    return None


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:32]
