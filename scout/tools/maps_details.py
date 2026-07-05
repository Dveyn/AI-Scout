from __future__ import annotations

import re

from playwright.async_api import async_playwright

from scout.config import get_settings
from scout.models.contacts import LeadContacts
from scout.tools.contact_extractor import contacts_from_maps_data
from scout.tools.email_extractor import EMAIL_PATTERN

PHONE_PATTERN = re.compile(
    r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)


async def fetch_maps_contacts(maps_url: str) -> LeadContacts:
    """Extract all contact channels from a Yandex Maps organization page."""
    if not maps_url:
        return LeadContacts()

    settings = get_settings()
    emails: list[str] = []
    phones: list[str] = []
    links: list[str] = []
    website: str | None = None
    body_text = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.playwright_headless)
        try:
            page = await browser.new_page(locale="ru-RU")
            await page.goto(maps_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            body_text = await page.inner_text("body") or ""
            emails.extend(EMAIL_PATTERN.findall(body_text))

            for el in await page.query_selector_all("a[href]"):
                href = await el.get_attribute("href")
                if not href:
                    continue
                href = href.strip()
                lower = href.lower()
                if href.startswith("mailto:"):
                    emails.append(href.replace("mailto:", "").split("?")[0])
                elif href.startswith("tel:"):
                    phones.append(href.replace("tel:", ""))
                elif any(x in lower for x in ("t.me/", "telegram.me/", "vk.com/", "max.ru", "wa.me", "whatsapp")):
                    links.append(href)
                elif href.startswith("http") and "yandex" not in lower:
                    links.append(href)

            for match in PHONE_PATTERN.findall(body_text):
                phones.append(match)

            for sel in (
                "a[aria-label*='Сайт']",
                "[class*='business-urls-view'] a[href^='http']",
                "[class*='business-contacts-view'] a[href^='http']",
            ):
                el = await page.query_selector(sel)
                if not el:
                    continue
                href = await el.get_attribute("href")
                if href and "yandex" not in href.lower():
                    if any(
                        x in href.lower()
                        for x in ("vk.com", "t.me", "telegram", "max.ru", "wa.me", "instagram", "facebook")
                    ):
                        links.append(href)
                    elif not website:
                        website = href

            if not website:
                for link in links:
                    lower = link.lower()
                    if any(
                        skip in lower
                        for skip in (
                            "vk.com",
                            "t.me",
                            "telegram",
                            "max.ru",
                            "wa.me",
                            "whatsapp",
                            "instagram",
                            "facebook",
                            "youtube",
                        )
                    ):
                        continue
                    website = link
                    break
        except Exception:
            return contacts_from_maps_data(emails=emails, phones=phones, links=links, body_text=body_text)
        finally:
            await browser.close()

    contacts = contacts_from_maps_data(
        emails=emails,
        phones=phones,
        links=links,
        body_text=body_text,
    )
    if website and website not in contacts.other_links:
        contacts.other_links.insert(0, website)
    return contacts


async def fetch_maps_website(maps_url: str) -> str | None:
    contacts = await fetch_maps_contacts(maps_url)
    for link in contacts.other_links:
        lower = link.lower()
        if not any(x in lower for x in ("vk.com", "t.me", "max.ru", "wa.me")):
            return link
    return None
