from __future__ import annotations

import logging
from datetime import datetime

from scout.config import get_settings
from scout.models.contacts import LeadContacts
from scout.models.schemas import JobReport, LeadRecord, SendStatus
from scout.outreach.channel_links import best_manual_channel, build_outreach_channels
from scout.outreach.dedup import contact_key
from scout.outreach.email_guard import is_sendable_email
from scout.outreach.rate_limiter import can_send_email, mark_sent, wait_before_send
from scout.outreach.sender import EmailSendError, send_email
from scout.storage import db

logger = logging.getLogger(__name__)


def _dedup_key(lead: LeadRecord) -> str | None:
    contacts = lead.contacts or LeadContacts()
    tg = contacts.telegram[0] if contacts.telegram else None
    vk = contacts.vk[0] if contacts.vk else None
    return contact_key(
        lead.email or lead.raw.email,
        lead.raw.phone,
        telegram=tg,
        vk=vk,
    )


def _touch_content(lead: LeadRecord, touch: int) -> tuple[str | None, str | None]:
    if touch == 1:
        if not lead.result:
            return None, None
        return lead.result.subject, lead.result.message
    for fu in lead.followups:
        if fu.touch == touch:
            return fu.subject, fu.message
    return None, None


def _touch_already_sent(lead: LeadRecord, touch: int) -> bool:
    if touch == 1:
        return lead.send_status == SendStatus.SENT
    for fu in lead.followups:
        if fu.touch == touch and fu.send_status == SendStatus.SENT:
            return True
    return False


async def prepare_outreach_channels(lead: LeadRecord, *, touch: int = 1) -> LeadRecord:
    subject, message = _touch_content(lead, touch)
    if not message:
        return lead
    contacts = lead.contacts or LeadContacts()
    lead.outreach_channels = build_outreach_channels(
        contacts,
        message,
        subject=subject,
        email=lead.email or lead.raw.email,
    )
    return lead


async def send_lead_outreach(lead_id: str, *, force: bool = False, touch: int = 1) -> LeadRecord:
    lead = await db.get_lead(lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    if _touch_already_sent(lead, touch) and not force:
        return lead

    subject, message = _touch_content(lead, touch)
    if not lead.result or not lead.result.is_target or not message:
        if touch == 1:
            lead.send_status = SendStatus.SKIPPED
            lead.send_error = "Не target или нет текста"
            await db.update_lead(lead)
            await db.log_outreach(
                lead, channel="none", status=lead.send_status, error=lead.send_error, touch_number=touch
            )
        return lead

    lead = await prepare_outreach_channels(lead, touch=touch)
    key = _dedup_key(lead)

    # Дедуп только для первого касания между кампаниями
    if touch == 1 and key and await db.was_contact_sent(key) and not force:
        lead.send_status = SendStatus.DUPLICATE
        lead.send_error = "Уже писали на этот контакт"
        await db.update_lead(lead)
        await db.log_outreach(
            lead, channel="dedup", status=lead.send_status, error=lead.send_error, touch_number=touch
        )
        return lead

    email = lead.email or lead.raw.email
    if email and subject:
        ok, err = is_sendable_email(email)
        if not ok:
            lead.send_status = SendStatus.SKIPPED
            lead.send_error = err
            await db.update_lead(lead)
            await db.log_outreach(
                lead, channel="email", status=SendStatus.SKIPPED, error=err, touch_number=touch
            )
            return lead

        allowed, limit_err = can_send_email(email)
        if not allowed:
            lead.send_status = SendStatus.SKIPPED
            lead.send_error = limit_err
            await db.update_lead(lead)
            await db.log_outreach(
                lead,
                channel="email",
                status=SendStatus.SKIPPED,
                error=limit_err,
                touch_number=touch,
            )
            return lead

        settings = get_settings()
        if (
            touch == 1
            and lead.result
            and lead.result.fit_score < settings.auto_send_min_fit_score
        ):
            lead.send_error = (
                f"Fit {lead.result.fit_score} < порога автоотправки "
                f"{settings.auto_send_min_fit_score} — отправьте вручную"
            )
            await db.update_lead(lead)
            return lead

        try:
            await wait_before_send()
            await send_email(email, subject, message)
            mark_sent(email)
            now = datetime.utcnow()
            if touch == 1:
                lead.send_status = SendStatus.SENT
                lead.send_error = None
                lead.sent_at = now
                lead.sequence_touch_sent = max(lead.sequence_touch_sent, 1)
                if key:
                    await db.mark_contact_sent(key, lead)
            else:
                lead.followups = [
                    fu.model_copy(
                        update={"send_status": SendStatus.SENT, "sent_at": now}
                        if fu.touch == touch
                        else {}
                    )
                    for fu in lead.followups
                ]
                lead.sequence_touch_sent = max(lead.sequence_touch_sent, touch)
            await db.update_lead(lead)
            await db.update_lead_result(lead)
            await db.log_outreach(
                lead,
                channel="email",
                status=SendStatus.SENT,
                touch_number=touch,
                subject=subject,
                message_preview=message[:200],
            )
            return lead
        except EmailSendError as exc:
            logger.warning("Email failed for %s touch %s: %s", lead.raw.name, touch, exc)
            if touch == 1:
                lead.send_status = SendStatus.FAILED
                lead.send_error = str(exc)
                await db.update_lead(lead)
                await db.log_outreach(
                    lead, channel="email", status=SendStatus.FAILED, error=str(exc), touch_number=touch
                )
            return lead

    if touch == 1:
        manual = best_manual_channel(lead.outreach_channels)
        if manual:
            lead.send_status = SendStatus.READY
            lead.send_error = None
            lead.fallback_text = manual.url
            await db.update_lead(lead)
            await db.log_outreach(
                lead,
                channel=manual.channel,
                status=SendStatus.READY,
                error=f"Ручной выход: {manual.label}",
                touch_number=touch,
            )
            return lead

        lead.send_status = SendStatus.NO_EMAIL
        lead.send_error = "Контакты не найдены — только карточка на картах"
        await db.update_lead(lead)
        await db.log_outreach(lead, channel="none", status=SendStatus.NO_EMAIL, touch_number=touch)
    return lead


async def mark_lead_sent_manual(lead_id: str, channel: str, *, touch: int = 1) -> LeadRecord:
    lead = await db.get_lead(lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    now = datetime.utcnow()
    if touch == 1:
        lead.send_status = SendStatus.SENT
        lead.send_error = None
        lead.sent_at = now
        lead.sequence_touch_sent = max(lead.sequence_touch_sent, 1)
    else:
        lead.followups = [
            fu.model_copy(update={"send_status": SendStatus.SENT, "sent_at": now})
            if fu.touch == touch
            else fu
            for fu in lead.followups
        ]
        lead.sequence_touch_sent = max(lead.sequence_touch_sent, touch)

    await db.update_lead(lead)
    await db.update_lead_result(lead)

    key = _dedup_key(lead)
    if touch == 1 and key:
        await db.mark_contact_sent(key, lead)

    subject, message = _touch_content(lead, touch)
    await db.log_outreach(
        lead,
        channel=channel,
        status=SendStatus.SENT,
        error="отмечено вручную",
        touch_number=touch,
        subject=subject,
        message_preview=message[:200] if message else None,
    )
    return lead


async def send_job_outreach(job_id: str, *, force: bool = False, touch: int = 1) -> JobReport:
    leads = await db.list_leads(job_id)
    for lead in leads:
        if not lead.result or not lead.result.is_target:
            continue
        if touch == 1 and lead.send_status == SendStatus.SENT and not force:
            continue
        if touch > 1 and _touch_already_sent(lead, touch) and not force:
            continue
        await send_lead_outreach(lead.id, force=force, touch=touch)

    report = await build_job_report(job_id)
    await db.update_job_report(job_id, report)
    return report


async def build_job_report(job_id: str) -> JobReport:
    leads = await db.list_leads(job_id)
    report = JobReport(job_id=job_id, collected=len(leads))

    for lead in leads:
        if lead.email or lead.raw.email or (lead.contacts and lead.contacts.emails):
            report.email_found += 1
        if lead.result and lead.result.is_target:
            report.targets += 1
        if lead.send_status == SendStatus.SENT:
            report.sent += 1
        elif lead.send_status == SendStatus.READY:
            report.ready_manual += 1
        elif lead.send_status == SendStatus.NO_EMAIL:
            report.no_contact += 1
            report.no_email += 1
        elif lead.send_status == SendStatus.DUPLICATE:
            report.duplicate += 1
        elif lead.send_status == SendStatus.FAILED:
            report.failed += 1
        elif lead.send_status == SendStatus.SKIPPED:
            report.skipped += 1

    return report
