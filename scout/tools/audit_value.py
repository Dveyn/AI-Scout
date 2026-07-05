from __future__ import annotations

import re
from typing import Any

# Паттерн в тексте issue аудита → бизнес-ценность доработки
ISSUE_VALUE_RULES: list[tuple[str, str]] = [
    (
        r"HTTPS|небезопасн",
        "браузер не пугает клиентов — выше доверие и конверсия в заявку",
    ),
    (
        r"мобильн|viewport|телефон",
        "клиенты с телефона не уходят — больше заявок с мобильного трафика",
    ),
    (
        r"медленн|загрузк|тормоз",
        "страница открывается быстрее — меньше ушедших до просмотра услуг",
    ),
    (
        r"title|SEO|description|сниппет|H1|поиск",
        "лучше видимость в Яндексе — больше целевых обращений без рекламы",
    ),
    (
        r"контакт|телефон|email|форма",
        "проще оставить заявку — меньше звонков «где у вас форма»",
    ),
    (
        r"alt|картинк|доступност",
        "аккуратнее в поиске и для клиентов — плюс к доверию к бренду",
    ),
    (
        r"тяжёл|KB|вес",
        "сайт не отваливается на слабом интернете — не теряете региональных клиентов",
    ),
    (
        r"ошибк|HTTP|недоступ",
        "сайт стабильно работает — заявки не теряются из-за падений",
    ),
]

DEFAULT_VALUE = (
    "доработка сайта под заявки: понятнее услуги, проще связаться, больше доверия у новых клиентов"
)


def value_for_issue(issue: str) -> str | None:
    for pattern, value in ISSUE_VALUE_RULES:
        if re.search(pattern, issue, re.IGNORECASE):
            return value
    return None


def merge_audits(base: dict[str, Any], seo: dict[str, Any] | None) -> dict[str, Any]:
    """Объединяет быстрый Python-аудит и IndexLift SEO."""
    if not seo:
        return enrich_audit_with_business_value(base)

    merged = dict(base)
    base_score = int(base.get("quality_score") or 100)
    seo_score = int(seo.get("quality_score") or 100)
    merged["quality_score"] = min(base_score, seo_score)
    merged["grade"] = seo.get("grade")

    seen: set[str] = set()
    issues: list[str] = []
    for group in (seo.get("issues") or [], base.get("issues") or []):
        for issue in group:
            if issue and issue not in seen:
                issues.append(issue)
                seen.add(issue)
    merged["issues"] = issues[:8]
    merged["seo_audit"] = seo
    merged["indexlift_findings"] = seo.get("indexlift_findings")
    if seo.get("business_hooks"):
        merged["business_hooks"] = seo["business_hooks"]
    if seo.get("yandex_score") is not None:
        merged["yandex_seo_score"] = seo["yandex_score"]
    return enrich_audit_with_business_value(merged)


def enrich_audit_with_business_value(audit: dict[str, Any]) -> dict[str, Any]:
    """Добавляет в аудит связку проблема → ценность доработки для агента."""
    issues = audit.get("issues") or []
    fix_values: list[dict[str, str]] = []
    seen_values: set[str] = set()

    for issue in issues[:5]:
        value = value_for_issue(issue)
        if value and value not in seen_values:
            fix_values.append({"problem": issue, "value_if_fixed": value})
            seen_values.add(value)

    if not fix_values and issues:
        fix_values.append({"problem": issues[0], "value_if_fixed": DEFAULT_VALUE})
    elif not fix_values and audit.get("quality_score", 100) < 80:
        fix_values.append(
            {
                "problem": "Сайт можно усилить под заявки",
                "value_if_fixed": DEFAULT_VALUE,
            }
        )

    audit["fix_values"] = fix_values
    if fix_values:
        audit["value_pitch_hint"] = (
            "В письме свяжи 1–2 проблемы с выгодой для бизнеса: "
            + "; ".join(v["value_if_fixed"] for v in fix_values[:2])
        )
    return audit
