"""Предупреждения о незаполненной конфигурации для UI."""

from __future__ import annotations

from scout.config import get_settings


def system_warnings() -> list[dict[str, str]]:
    settings = get_settings()
    warnings: list[dict[str, str]] = []

    if not settings.gptunnel_api_key.strip():
        warnings.append(
            {
                "id": "gptunnel",
                "title": "GPTunnel не настроен",
                "text": "AI-письма не сгенерируются. Добавьте GPTUNNEL_API_KEY в scout/.env",
            }
        )
    elif settings.llm_daily_budget_rub > 0:
        warnings.append(
            {
                "id": "llm_budget",
                "title": f"Лимит GPTunnel: {settings.llm_daily_budget_rub:.0f} ₽/день",
                "text": "При исчерпании бюджета кампания остановится. AGENT_LITE_MODE=true экономит токены.",
            }
        )

    if not settings.smtp_host.strip() or not settings.smtp_user.strip():
        warnings.append(
            {
                "id": "smtp",
                "title": "Почта (SMTP) не настроена",
                "text": "Письма останутся черновиками в интерфейсе — заполните SMTP_* в scout/.env",
            }
        )

    if settings.revenue_filter_enabled and not settings.dadata_api_key.strip():
        warnings.append(
            {
                "id": "dadata",
                "title": "Фильтр выручки включён без DaData",
                "text": "Задайте DADATA_API_KEY или отключите REVENUE_FILTER_ENABLED",
            }
        )

    mode = (settings.maps_collector or "yandex").lower()
    if mode in ("2gis", "auto") and not settings.twogis_api_key.strip():
        warnings.append(
            {
                "id": "2gis",
                "title": "2GIS API не настроен",
                "text": "Сбор идёт через Яндекс.Карты (Playwright). Для официального API — TWOGIS_API_KEY",
            }
        )

    return warnings
