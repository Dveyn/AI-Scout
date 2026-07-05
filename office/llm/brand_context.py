from __future__ import annotations

from functools import lru_cache

from office.config import get_office_settings
from office.models import ModelTier

_BRAND_CACHE: str | None = None


def load_brand_context() -> str:
    global _BRAND_CACHE
    if _BRAND_CACHE is not None:
        return _BRAND_CACHE
    path = get_office_settings().brand_path()
    if path.is_file():
        _BRAND_CACHE = path.read_text(encoding="utf-8")
    else:
        _BRAND_CACHE = "ВебШтрих — B2B веб-студия, Ростов-на-Дону."
    return _BRAND_CACHE


def cached_system_prefix(role: str) -> str:
    """Stable prefix for prompt caching — brand + role."""
    return f"{load_brand_context()}\n\n---\nРоль: {role}\n"


def invalidate_brand_cache() -> None:
    global _BRAND_CACHE
    _BRAND_CACHE = None


@lru_cache
def model_for_tier(tier: ModelTier) -> str:
    settings = get_office_settings()
    if tier == ModelTier.STRATEGY:
        return settings.gptunnel_model_strategy
    return settings.gptunnel_model_execution
