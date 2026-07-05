from __future__ import annotations

import re

import httpx
import trafilatura

MAX_TEXT_LEN = 1500
TIMEOUT = 8.0


async def fetch_website(url: str) -> dict[str, str | None]:
    """Fetch website title, description and visible text."""
    if not url:
        return {"error": "URL не указан", "title": None, "description": None, "text": None}

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIScout/1.0)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        return {
            "error": str(exc),
            "title": None,
            "description": None,
            "text": None,
            "url": url,
        }

    downloaded = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        output_format="txt",
    )
    text = (downloaded or "")[:MAX_TEXT_LEN]

    title = None
    description = None
    title_match = re.search(
        r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE
    )
    if title_match:
        title = title_match.group(1).strip()

    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
        html,
        re.IGNORECASE,
    )
    if desc_match:
        description = desc_match.group(1).strip()

    return {
        "url": url,
        "title": title,
        "description": description,
        "text": text or None,
        "error": None,
    }
