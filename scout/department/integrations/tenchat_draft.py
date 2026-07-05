from __future__ import annotations

import logging
from pathlib import Path

from scout.config import SCOUT_ROOT

logger = logging.getLogger(__name__)
TENCHAT_DIR = SCOUT_ROOT / "data" / "content" / "tenchat"


def save_tenchat_draft(post_id: str, text: str) -> bool:
    TENCHAT_DIR.mkdir(parents=True, exist_ok=True)
    path = TENCHAT_DIR / f"{post_id}.txt"
    path.write_text(text, encoding="utf-8")
    logger.info("TenChat draft saved: %s", path)
    return True
