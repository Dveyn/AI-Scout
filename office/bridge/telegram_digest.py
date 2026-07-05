from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def send_standup_digest(text: str) -> bool:
    try:
        from scout.notify.telegram import send_telegram

        return await send_telegram(text)
    except Exception as exc:
        logger.warning("telegram digest failed: %s", exc)
        return False
