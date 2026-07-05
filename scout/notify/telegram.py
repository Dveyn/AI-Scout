from __future__ import annotations

import logging

import httpx

from scout.config import get_settings

logger = logging.getLogger(__name__)


async def send_telegram(text: str, *, parse_mode: str | None = None) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict = {
        "chat_id": settings.telegram_chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            return resp.is_success
    except Exception as exc:
        logger.warning("Telegram notify failed: %s", exc)
        return False
