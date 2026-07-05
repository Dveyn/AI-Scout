from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

TIMEOUT = 12.0
USER_AGENT = "Mozilla/5.0 (compatible; AIScout/1.0; +https://github.com/)"


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _meta_content(html: str, name: str) -> str | None:
    pattern = rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)'
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    pattern2 = rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(name)}["\']'
    m2 = re.search(pattern2, html, re.IGNORECASE)
    return m2.group(1).strip() if m2 else None


def _count_pattern(html: str, pattern: str) -> int:
    return len(re.findall(pattern, html, re.IGNORECASE))


def _analyze_html(url: str, html: str, status_code: int, elapsed_ms: int) -> dict[str, Any]:
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_m.group(1).strip() if title_m else None
    description = _meta_content(html, "description")
    viewport = _meta_content(html, "viewport")

    h1_count = _count_pattern(html, r"<h1[\s>]")
    img_count = _count_pattern(html, r"<img[\s>]")
    img_no_alt = _count_pattern(html, r"<img(?![^>]*\balt=)[^>]*>")
    img_empty_alt = _count_pattern(html, r'<img[^>]+alt=["\']\s*["\']')
    images_without_alt = img_no_alt + img_empty_alt

    has_phone = bool(re.search(r'href=["\']tel:', html, re.IGNORECASE))
    has_email = bool(re.search(r'href=["\']mailto:', html, re.IGNORECASE))
    has_form = bool(re.search(r"<form[\s>]", html, re.IGNORECASE))
    has_whatsapp = "wa.me" in html.lower() or "whatsapp" in html.lower()

    page_size_kb = round(len(html.encode("utf-8", errors="ignore")) / 1024, 1)
    uses_https = url.lower().startswith("https://")

    issues: list[str] = []
    strengths: list[str] = []

    score = 100

    if status_code >= 400:
        issues.append(f"Сайт отвечает с ошибкой HTTP {status_code}")
        score -= 40
    elif status_code >= 300:
        issues.append(f"Редирект HTTP {status_code} — проверьте финальный URL")
        score -= 5

    if not uses_https:
        issues.append("Нет HTTPS — браузер помечает сайт как небезопасный")
        score -= 15
    else:
        strengths.append("Есть HTTPS")

    if elapsed_ms > 3000:
        issues.append(f"Медленная загрузка (~{elapsed_ms} мс) — часть клиентов уйдёт")
        score -= 15
    elif elapsed_ms > 1500:
        issues.append(f"Загрузка средняя ({elapsed_ms} мс), есть куда ускорить")
        score -= 8
    else:
        strengths.append(f"Быстрая загрузка ({elapsed_ms} мс)")

    if not title:
        issues.append("Нет тега <title> — хуже SEO и вкладка в браузере пустая")
        score -= 12
    elif len(title) < 15:
        issues.append(f"Слишком короткий title («{title[:40]}») — слабое SEO")
        score -= 6
    else:
        strengths.append("Заполнен title")

    if not description:
        issues.append("Нет meta description — сниппет в поиске будет случайным")
        score -= 10
    elif len(description) < 50:
        issues.append("Meta description слишком короткое")
        score -= 5
    else:
        strengths.append("Есть meta description")

    if not viewport:
        issues.append("Нет meta viewport — сайт, вероятно, плохо выглядит на телефоне")
        score -= 18
    else:
        strengths.append("Есть viewport (мобильная вёрстка)")

    if h1_count == 0:
        issues.append("Нет заголовка H1 — слабая структура и SEO")
        score -= 10
    elif h1_count > 1:
        issues.append(f"Несколько H1 ({h1_count}) — размывает фокус страницы")
        score -= 5

    if img_count > 0:
        ratio = images_without_alt / img_count
        if ratio > 0.5:
            issues.append(
                f"{images_without_alt} из {img_count} картинок без alt — минус к SEO и доступности"
            )
            score -= 10

    if page_size_kb > 1500:
        issues.append(f"Тяжёлая страница ({page_size_kb} KB) — тормозит на мобильном")
        score -= 8

    if not any([has_phone, has_email, has_form, has_whatsapp]):
        issues.append("Не видно контактов на главной (телефон/email/форма)")
        score -= 12
    else:
        contact_bits = []
        if has_phone:
            contact_bits.append("телефон")
        if has_email:
            contact_bits.append("email")
        if has_form:
            contact_bits.append("форма")
        if has_whatsapp:
            contact_bits.append("WhatsApp")
        strengths.append("Контакты на странице: " + ", ".join(contact_bits))

    score = max(0, min(100, score))

    return {
        "url": url,
        "status_code": status_code,
        "response_time_ms": elapsed_ms,
        "uses_https": uses_https,
        "title": title,
        "description": description,
        "has_viewport": bool(viewport),
        "h1_count": h1_count,
        "images_total": img_count,
        "images_without_alt": images_without_alt,
        "has_phone_link": has_phone,
        "has_email_link": has_email,
        "has_contact_form": has_form,
        "page_size_kb": page_size_kb,
        "quality_score": score,
        "issues": issues,
        "strengths": strengths,
        "error": None,
    }


async def audit_website(url: str) -> dict[str, Any]:
    """Basic technical quality audit of a company website."""
    if not url:
        return {"error": "URL не указан", "quality_score": 0, "issues": ["Сайт не указан"]}

    url = _normalize_url(url)

    try:
        start = time.perf_counter()
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            final_url = str(response.url)
            html = response.text
    except Exception as exc:
        return {
            "url": url,
            "error": str(exc),
            "quality_score": 0,
            "issues": [f"Сайт недоступен: {exc}"],
            "strengths": [],
        }

    result = _analyze_html(final_url, html, response.status_code, elapsed_ms)
    if urlparse(final_url).netloc != urlparse(url).netloc:
        result["redirected_from"] = url
        result["final_url"] = final_url
    return result
