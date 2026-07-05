from __future__ import annotations

import logging

from scout.collectors.twogis import TwogisCollector
from scout.collectors.yandex_maps import YandexMapsCollector
from scout.config import get_settings

logger = logging.getLogger(__name__)


def get_maps_collector():
    """yandex = Playwright; 2gis = официальный API; auto = 2GIS если есть ключ."""
    settings = get_settings()
    mode = (settings.maps_collector or "yandex").strip().lower()

    if mode in ("2gis", "twogis") or (mode == "auto" and settings.twogis_api_key):
        if settings.twogis_api_key:
            logger.info("Collector: 2GIS API")
            return TwogisCollector()
        logger.warning("MAPS_COLLECTOR=%s но TWOGIS_API_KEY пуст — fallback на Яндекс.Карты", mode)

    logger.info("Collector: Яндекс.Карты (Playwright)")
    return YandexMapsCollector()


def collector_label() -> str:
    settings = get_settings()
    mode = (settings.maps_collector or "yandex").strip().lower()
    if mode in ("2gis", "twogis") or (mode == "auto" and settings.twogis_api_key):
        if settings.twogis_api_key:
            return "2GIS API"
    return "Яндекс.Карты"
