from __future__ import annotations

import logging

import httpx

from scout.config import get_settings

logger = logging.getLogger(__name__)


async def publish_vk_post(text: str) -> bool:
    settings = get_settings()
    if not settings.vk_access_token or not settings.vk_group_id:
        logger.info("VK not configured, skipping publish")
        return False
    url = "https://api.vk.com/method/wall.post"
    params = {
        "access_token": settings.vk_access_token,
        "owner_id": f"-{settings.vk_group_id.lstrip('-')}",
        "from_group": 1,
        "message": text[:4000],
        "v": "5.131",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=params)
            data = resp.json()
            if "error" in data:
                logger.warning("VK API error: %s", data["error"])
                return False
            return True
    except Exception as exc:
        logger.warning("VK publish failed: %s", exc)
        return False
