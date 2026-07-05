from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote_plus

from playwright.async_api import Page, async_playwright

from scout.config import get_settings
from scout.models.schemas import RawLead
from scout.storage.company_dedup import company_keys, matches_scanned

logger = logging.getLogger(__name__)

MAX_SCROLL_ATTEMPTS = 8
MAX_SCROLL_ATTEMPTS_WITH_EXCLUDES = 16


class YandexMapsCollector:
    """Playwright-based collector for Yandex Maps business listings."""

    async def collect(
        self,
        query: str,
        city: str,
        limit: int,
        *,
        exclude_keys: set[str] | None = None,
    ) -> list[RawLead]:
        search_text = f"{query} {city}".strip()
        settings = get_settings()
        known = exclude_keys or set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.playwright_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = await browser.new_page(
                    locale="ru-RU",
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                url = f"https://yandex.ru/maps/?text={quote_plus(search_text)}"
                logger.info("Yandex Maps search: %s", search_text)
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2500)

                await self._wait_for_results(page)
                leads, skipped_known = await self._collect_from_list(page, limit, known)
            finally:
                await browser.close()

        if skipped_known:
            logger.info(
                "Collected %d new leads (%d already scanned, skipped)",
                len(leads),
                skipped_known,
            )
        else:
            logger.info("Collected %d leads", len(leads))
        return leads[:limit]

    async def _wait_for_results(self, page: Page) -> None:
        selectors = [
            ".search-snippet-view",
            "[class*='search-snippet-view']",
            "[class*='search-business-snippet']",
        ]
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=20000)
                return
            except Exception:
                continue
        logger.warning("Search results selector not found, continuing anyway")

    async def _collect_from_list(
        self,
        page: Page,
        limit: int,
        exclude_keys: set[str],
    ) -> tuple[list[RawLead], int]:
        leads: list[RawLead] = []
        seen_keys: set[str] = set()
        skipped_known = 0
        max_attempts = MAX_SCROLL_ATTEMPTS_WITH_EXCLUDES if exclude_keys else MAX_SCROLL_ATTEMPTS
        scroll_attempts = 0

        while len(leads) < limit and scroll_attempts < max_attempts:
            items = await self._find_list_items(page)
            added_this_round = 0

            for item in items:
                if len(leads) >= limit:
                    break
                lead = await self._parse_list_item_fast(item)
                if not lead:
                    continue
                if matches_scanned(lead, seen_keys):
                    continue
                if matches_scanned(lead, exclude_keys):
                    skipped_known += 1
                    continue
                for key in company_keys(lead):
                    seen_keys.add(key)
                leads.append(lead)
                added_this_round += 1
                await asyncio.sleep(0.2)

            if len(leads) >= limit:
                break

            if added_this_round == 0:
                scroll_attempts += 1
            else:
                scroll_attempts = 0

            if not await self._load_more(page):
                break
            await asyncio.sleep(1)

        return leads, skipped_known

    async def _find_list_items(self, page: Page):
        for sel in (
            ".search-snippet-view",
            "[class*='search-snippet-view']",
            "[class*='search-business-snippet']",
        ):
            items = await page.query_selector_all(sel)
            if items:
                return items
        return []

    async def _load_more(self, page: Page) -> bool:
        for sel in (
            "button:has-text('Показать ещё')",
            "button:has-text('Показать еще')",
        ):
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue

        for sel in (
            ".scroll__container",
            "[class*='scroll__container']",
            "[class*='search-list-view__list']",
        ):
            try:
                list_el = await page.query_selector(sel)
                if list_el:
                    prev = await list_el.evaluate("el => el.scrollTop")
                    await list_el.evaluate("el => { el.scrollTop = el.scrollHeight; }")
                    await page.wait_for_timeout(1500)
                    new = await list_el.evaluate("el => el.scrollTop")
                    return new > prev
            except Exception:
                continue
        return False

    async def _parse_list_item_fast(self, item) -> RawLead | None:
        """Parse listing card without opening each org in a new tab."""
        try:
            name_el = await item.query_selector(
                "[class*='search-business-snippet-view__title'], "
                "[class*='business-card-title-view__title'], "
                "a[href*='/org/']"
            )
            name = await self._text(name_el)
            if not name:
                return None

            category_el = await item.query_selector(
                "[class*='search-business-snippet-view__category'], "
                "[class*='business-categories-view']"
            )
            category = await self._text(category_el)

            address_el = await item.query_selector(
                "[class*='search-business-snippet-view__address'], "
                "[class*='business-contacts-view__address']"
            )
            address = await self._text(address_el)

            rating = None
            reviews_count = None
            rating_el = await item.query_selector(
                "[class*='business-rating-badge-view__rating'], "
                "[class*='rating__value']"
            )
            rating_text = await self._text(rating_el)
            if rating_text:
                m = re.search(r"([\d.,]+)", rating_text.replace(",", "."))
                if m:
                    try:
                        rating = float(m.group(1))
                    except ValueError:
                        pass

            reviews_el = await item.query_selector(
                "[class*='business-rating-badge-view__count'], "
                "[class*='rating__count']"
            )
            reviews_text = await self._text(reviews_el)
            if reviews_text:
                m = re.search(r"(\d+)", reviews_text.replace(" ", ""))
                if m:
                    reviews_count = int(m.group(1))

            link_el = await item.query_selector("a[href*='/org/']")
            maps_url = None
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    maps_url = href if href.startswith("http") else f"https://yandex.ru{href}"

            snippet_el = await item.query_selector(
                "[class*='business-review-view'], [class*='snippet-view']"
            )
            snippet = await self._text(snippet_el)

            phone_el = await item.query_selector("a[href^='tel:']")
            phone = None
            if phone_el:
                href = await phone_el.get_attribute("href")
                phone = (await self._text(phone_el)) or (
                    href.replace("tel:", "") if href else None
                )

            email = None
            mailto_el = await item.query_selector("a[href^='mailto:']")
            if mailto_el:
                href = await mailto_el.get_attribute("href")
                if href:
                    email = href.replace("mailto:", "").split("?")[0].strip().lower()

            return RawLead(
                name=name,
                category=category,
                address=address,
                phone=phone,
                email=email,
                website=None,
                rating=rating,
                reviews_count=reviews_count,
                maps_url=maps_url,
                snippet=snippet,
                source="yandex",
            )
        except Exception:
            logger.exception("Failed to parse list item")
            return None

    async def _text(self, el) -> str | None:
        if not el:
            return None
        text = (await el.inner_text()).strip()
        return text or None
