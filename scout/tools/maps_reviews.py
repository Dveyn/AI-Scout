from __future__ import annotations

import re

from playwright.async_api import async_playwright

from scout.config import get_settings


async def fetch_maps_reviews(maps_url: str, limit: int = 5) -> dict:
    """Fetch top reviews from a Yandex Maps organization page."""
    if not maps_url:
        return {"error": "maps_url не указан", "reviews": []}

    settings = get_settings()
    reviews: list[dict[str, str]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.playwright_headless)
        try:
            page = await browser.new_page(locale="ru-RU")
            await page.goto(maps_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)

            # Try to open reviews tab
            for sel in [
                "button:has-text('Отзывы')",
                "a:has-text('Отзывы')",
                "[class*='tabs'] :has-text('Отзывы')",
            ]:
                try:
                    tab = await page.query_selector(sel)
                    if tab and await tab.is_visible():
                        await tab.click()
                        await page.wait_for_timeout(2000)
                        break
                except Exception:
                    continue

            review_els = await page.query_selector_all(
                "[class*='business-review-view'], [class*='review-item']"
            )
            for el in review_els[:limit]:
                text_el = await el.query_selector(
                    "[class*='business-review-view__body'], "
                    "[class*='review-item__text'], "
                    "[class*='review-text']"
                )
                author_el = await el.query_selector(
                    "[class*='business-review-view__author'], "
                    "[class*='review-item__author']"
                )
                rating_el = await el.query_selector(
                    "[class*='business-rating-badge-view__rating'], "
                    "[class*='stars']"
                )
                text = await _inner(text_el)
                author = await _inner(author_el)
                rating_text = await _inner(rating_el)
                rating = None
                if rating_text:
                    m = re.search(r"([\d.,]+)", rating_text.replace(",", "."))
                    if m:
                        try:
                            rating = float(m.group(1))
                        except ValueError:
                            pass
                if text:
                    reviews.append(
                        {
                            "author": author or "Аноним",
                            "rating": str(rating) if rating else None,
                            "text": text[:500],
                        }
                    )
        except Exception as exc:
            return {"error": str(exc), "reviews": reviews, "maps_url": maps_url}
        finally:
            await browser.close()

    return {"maps_url": maps_url, "reviews": reviews, "error": None}


async def _inner(el) -> str | None:
    if not el:
        return None
    t = (await el.inner_text()).strip()
    return t or None
