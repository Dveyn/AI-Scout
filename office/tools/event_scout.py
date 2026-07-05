from __future__ import annotations

import json
import logging
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; WebStrokeOffice/1.0)"
TIMEOUT = 15.0

DEFAULT_QUERIES = [
    "мастер-класс вебинар для предпринимателей B2B 2026",
    "онлайн конференция малый бизнес digital маркетинг",
    "вебинар интернет-магазин B2B продажи",
    "мастер класс 1С CRM интеграция вебинар",
    "онлайн мероприятие владельцы бизнеса сайт заявки",
    "вебинар e-commerce опт производство",
]

EVENT_KEYWORDS = re.compile(
    r"вебинар|мастер.?класс|конференц|форум|meetup|саммит|"
    r"webinar|masterclass|conference|онлайн.?меропр",
    re.I,
)

RESULT_LINK = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.I | re.S,
)
RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.I | re.S,
)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    return unescape(TAG_RE.sub("", text)).strip()


def _unwrap_ddg_url(href: str) -> str:
    if "uddg=" in href:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


async def _duckduckgo_search(query: str, *, max_results: int = 6) -> list[dict[str, str]]:
    url = "https://html.duckduckgo.com/html/"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.post(url, data={"q": query, "b": ""})
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        logger.warning("DDG search failed for %r: %s", query, exc)
        return []

    links = RESULT_LINK.findall(html)
    snippets = RESULT_SNIPPET.findall(html)
    results: list[dict[str, str]] = []
    for i, (href, title) in enumerate(links[:max_results]):
        title_clean = _clean_html(title)
        snippet = _clean_html(snippets[i]) if i < len(snippets) else ""
        real_url = _unwrap_ddg_url(href)
        if not title_clean or not real_url.startswith("http"):
            continue
        if not EVENT_KEYWORDS.search(f"{title_clean} {snippet}"):
            continue
        results.append(
            {
                "title": title_clean[:300],
                "url": real_url[:500],
                "snippet": snippet[:500],
                "query": query,
            }
        )
    return results


async def search_online_events(
    *,
    extra_queries: list[str] | None = None,
    max_per_query: int = 5,
) -> list[dict[str, str]]:
    """Collect candidate online events from web search (no API key)."""
    queries = list(DEFAULT_QUERIES)
    if extra_queries:
        queries = extra_queries + queries

    seen_urls: set[str] = set()
    merged: list[dict[str, str]] = []
    for query in queries[:8]:
        for item in await _duckduckgo_search(query, max_results=max_per_query):
            key = item["url"].split("?")[0].rstrip("/").lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(item)
    return merged


def build_events_extraction_prompt(candidates: list[dict[str, str]], brief: str = "") -> str:
    lines = []
    for i, c in enumerate(candidates[:25], 1):
        lines.append(
            f"{i}. {c['title']}\n   URL: {c['url']}\n   Сниппет: {c.get('snippet', '')}"
        )
    corpus = "\n\n".join(lines) or "Кандидатов не найдено."
    return f"""Ты — аналитик B2B-веб-студии ВебШтрих (сайты, B2B-порталы, 1С, заявки для малого и среднего B2B в РФ).

Задача CEO: {brief or "Собрать онлайн-мероприятия, где будут потенциальные клиенты (владельцы/директора/коммерция SMB, маркетологи)."}

Ниже результаты поиска. Извлеки ТОЛЬКО реальные онлайн-мероприятия (вебинар, мастер-класс, конференция, форум).
Не выдумывай URL и даты. Если даты нет в сниппете — оставь date пустым.

Верни JSON-массив (без markdown):
[
  {{
    "title": "название",
    "url": "ссылка",
    "event_type": "webinar|masterclass|conference|forum|other",
    "date_hint": "как указано в тексте или пусто",
    "audience": "кто целевая аудитория",
    "relevance": 1-10,
    "why_relevant": "почему полезно для ВебШтрих",
    "registration_hint": "как записаться если видно"
  }}
]

Максимум 12 лучших по relevance. Пропускай агрегаторы без конкретного события.

Данные поиска:
{corpus}
"""


def parse_events_json(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and item.get("title"):
            out.append(item)
    return out
