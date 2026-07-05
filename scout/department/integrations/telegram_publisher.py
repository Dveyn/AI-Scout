from __future__ import annotations

import logging

import httpx

from scout.config import get_settings

logger = logging.getLogger(__name__)


async def publish_telegram_channel(text: str) -> bool:
    settings = get_settings()
    chat_id = settings.telegram_channel_id or settings.telegram_chat_id
    if not settings.telegram_bot_token or not chat_id:
        logger.info("Telegram channel not configured, skipping publish")
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            return resp.is_success
    except Exception as exc:
        logger.warning("Telegram publish failed: %s", exc)
        return False
