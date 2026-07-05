from __future__ import annotations

import logging

from scout.models.contacts import LeadContacts
from scout.models.schemas import AgentTraceStep, RawLead
from scout.tools.combined_audit import audit_website_full
from scout.tools.contact_extractor import extract_contacts_from_website, finalize_contacts
from scout.tools.email_extractor import pick_best_email
from scout.tools.maps_details import fetch_maps_contacts
from scout.tools.website import fetch_website

logger = logging.getLogger(__name__)


async def enrich_lead_with_website_audit(
    lead: RawLead,
    *,
    lite: bool = False,
) -> tuple[RawLead, dict | None, list[AgentTraceStep], LeadContacts, dict | None]:
    """Resolve website, contacts, audit; для lite — ещё текст сайта без повторного LLM-fetch."""
    trace: list[AgentTraceStep] = []
    updated = lead
    contacts = LeadContacts()

    if updated.maps_url:
        logger.info("Resolving contacts from maps for %s", updated.name)
        maps_contacts = await fetch_maps_contacts(updated.maps_url)
        contacts = contacts.merge(maps_contacts)

        website = None
        for link in maps_contacts.other_links:
            lower = link.lower()
            if not any(x in lower for x in ("vk.com", "t.me", "max.ru", "wa.me")):
                website = link
                break

        if website and not updated.website:
            updated = updated.model_copy(update={"website": website})
            trace.append(
                AgentTraceStep(
                    round=0,
                    type="preflight",
                    content=f"Сайт с карточки: {website}",
                    tool_name="fetch_maps_contacts",
                )
            )

        if maps_contacts.emails and not updated.email:
            email = maps_contacts.emails[0]
            updated = updated.model_copy(update={"email": email})
            trace.append(
                AgentTraceStep(
                    round=0,
                    type="preflight",
                    content=f"Email с карточки: {email}",
                    tool_name="fetch_maps_contacts",
                )
            )

        if maps_contacts.phones and not updated.phone:
            updated = updated.model_copy(update={"phone": maps_contacts.phones[0]})

        social_bits = []
        if maps_contacts.telegram:
            social_bits.append(f"TG @{maps_contacts.telegram[0]}")
        if maps_contacts.vk:
            social_bits.append("VK")
        if maps_contacts.max_links:
            social_bits.append("Max")
        if social_bits:
            trace.append(
                AgentTraceStep(
                    round=0,
                    type="preflight",
                    content="Каналы с карт: " + ", ".join(social_bits),
                    tool_name="fetch_maps_contacts",
                )
            )

    if updated.website:
        site_contacts = await extract_contacts_from_website(updated.website)
        contacts = contacts.merge(site_contacts)
        if site_contacts.lpr_name:
            trace.append(
                AgentTraceStep(
                    round=0,
                    type="preflight",
                    content=f"ЛПР на сайте: {site_contacts.lpr_name} ({site_contacts.lpr_role})",
                    tool_name="extract_contacts",
                )
            )

    contacts = finalize_contacts(contacts)
    if contacts.emails and not updated.email:
        updated = updated.model_copy(update={"email": contacts.emails[0]})
    if contacts.phones and not updated.phone:
        updated = updated.model_copy(update={"phone": contacts.phones[0]})

    audit: dict | None = None
    if updated.website:
        logger.info("Auditing website for %s: %s", updated.name, updated.website)
        audit = await audit_website_full(updated.website)
        issues = audit.get("issues") or []
        score = audit.get("quality_score", 0)
        source = audit.get("seo_audit", {}).get("source") or audit.get("source") or "python"
        preview = f"quality_score={score} ({source})"
        if issues:
            preview += "; " + "; ".join(issues[:3])
        trace.append(
            AgentTraceStep(
                round=0,
                type="preflight",
                content=f"Аудит сайта: {score}/100",
                tool_name="audit_website",
                tool_args={"url": updated.website},
                tool_result_preview=preview,
            )
        )

        if not updated.email:
            email = pick_best_email(contacts.emails) or await pick_best_email_from_site(updated.website)
            if email:
                updated = updated.model_copy(update={"email": email})
                if email not in contacts.emails:
                    contacts.emails.insert(0, email)
                trace.append(
                    AgentTraceStep(
                        round=0,
                        type="preflight",
                        content=f"Email с сайта: {email}",
                        tool_name="extract_email",
                    )
                )

    contacts = finalize_contacts(contacts)
    website_content: dict | None = None
    if lite and updated.website:
        website_content = await fetch_website(updated.website)
        if website_content.get("text"):
            trace.append(
                AgentTraceStep(
                    round=0,
                    type="preflight",
                    content="Текст сайта загружен для lite-режима",
                    tool_name="fetch_website",
                )
            )

    return updated, audit, trace, contacts, website_content


async def pick_best_email_from_site(url: str) -> str | None:
    from scout.tools.email_extractor import find_best_email

    return await find_best_email(url)
