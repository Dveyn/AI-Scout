from __future__ import annotations

import logging

from scout.agent.cost_guard import can_spend_llm, record_llm_cost
from scout.agent.enrichment import enrich_lead_with_website_audit
from scout.agent.followup_generator import generate_followups
from scout.agent.prefilter import PrefilterAction, PrefilterProfile, prefilter_lead
from scout.agent.scout_agent import ScoutAgent
from scout.collectors.factory import collector_label, get_maps_collector
from scout.enrichment.dadata import apply_revenue_to_lead
from scout.presets.loader import load_preset
from scout.config import get_settings
from scout.models.schemas import (
    AgentResult,
    AgentTraceStep,
    ICPConfig,
    JobStatus,
    LeadRecord,
    ProcessedLead,
    SendStatus,
)
from scout.models.contacts import LeadContacts
from scout.outreach.service import build_job_report, prepare_outreach_channels, send_job_outreach
from scout.storage import db
from scout.storage.company_dedup import company_keys, matches_scanned

logger = logging.getLogger(__name__)


async def process_job(job_id: str) -> None:
    job = await db.get_job(job_id)
    if not job:
        return

    settings = get_settings()
    product = job.product
    if job.offer:
        product = f"{job.product}\n\nКлючевое предложение:\n{job.offer}"
    elif settings.default_offer:
        product = f"{job.product}\n\nКлючевое предложение:\n{settings.default_offer}"

    skill = job.agent_skill or settings.agent_skill
    config = ICPConfig(
        icp=job.icp,
        product=product,
        offer=job.offer,
        query=job.query,
        city=job.city,
        limit=job.limit,
        tone=job.tone,
        auto_send=job.auto_send or settings.auto_send_email,
        agent_skill=skill,
        preset=job.preset,
        generate_followups=job.generate_followups,
    )

    try:
        job.status = JobStatus.COLLECTING
        job.progress_current = 0
        job.progress_total = config.limit
        await db.update_job(job)

        prefilter_profile = PrefilterProfile.B2B
        if job.preset:
            try:
                preset_data = load_preset(job.preset)
                raw_prof = str(preset_data.get("prefilter_profile", "b2b")).replace("-", "_")
                prefilter_profile = PrefilterProfile(raw_prof)
            except (FileNotFoundError, ValueError):
                pass

        source = collector_label()
        logger.info("Job %s: collecting from %s", job_id, source)
        scanned_keys = await db.list_scanned_company_keys()
        collector = get_maps_collector()
        raw_leads = await collector.collect(
            config.query,
            config.city,
            config.limit,
            exclude_keys=scanned_keys,
        )
        logger.info("Job %s: collected %d new leads", job_id, len(raw_leads))

        if not raw_leads:
            job.status = JobStatus.FAILED
            job.error = (
                f"Не удалось собрать новые организации ({source}). "
                "Возможно, все найденные компании уже анализировались ранее — "
                "попробуйте другой запрос, город или увеличьте лимит."
            )
            await db.update_job(job)
            return

        job.status = JobStatus.SCOUTING
        job.progress_current = 0
        job.progress_total = len(raw_leads)
        await db.update_job(job)

        agent = ScoutAgent(skill_name=skill)
        processed_count = 0
        skipped_prefilter = 0
        for raw in raw_leads:
            if matches_scanned(raw, scanned_keys):
                logger.info("Job %s: skip already scanned — %s", job_id, raw.name)
                continue

            if not can_spend_llm():
                logger.warning("Job %s: LLM daily budget reached, stopping early", job_id)
                break

            for key in company_keys(raw):
                scanned_keys.add(key)

            pf = prefilter_lead(raw, prefilter_profile)
            if pf.action == PrefilterAction.SKIP:
                skipped_prefilter += 1
                logger.info("Job %s: prefilter skip — %s (%s)", job_id, raw.name, pf.reason)
                await _save_skipped_lead(raw, job_id, pf.reason)
                processed_count += 1
                job.progress_current = processed_count
                await db.update_job(job)
                continue

            revenue_skip = await apply_revenue_to_lead(raw, config.city)
            if revenue_skip:
                skipped_prefilter += 1
                logger.info("Job %s: revenue filter — %s (%s)", job_id, raw.name, revenue_skip)
                await _save_skipped_lead(raw, job_id, revenue_skip)
                processed_count += 1
                job.progress_current = processed_count
                await db.update_job(job)
                continue

            processed_count += 1
            use_lite = settings.agent_lite_mode and pf.action == PrefilterAction.LITE
            logger.info(
                "Job %s: scouting %d/%d — %s [%s]",
                job_id,
                processed_count,
                len(raw_leads),
                raw.name,
                "lite" if use_lite else "full",
            )
            processed = await process_lead(
                agent,
                raw,
                config,
                job_id,
                use_lite=use_lite,
            )
            record_llm_cost(processed.llm_cost_rub)
            job.progress_current = processed_count
            job.llm_cost_rub += processed.llm_cost_rub
            await db.update_job(job)

        job.status = JobStatus.DONE
        job.error = None
        await db.update_job(job)

        report = await build_job_report(job_id)
        await db.update_job_report(job_id, report)
        logger.info(
            "Job %s: done — collected=%d skipped_prefilter=%d targets=%d llm=%.2f₽",
            job_id,
            report.collected,
            skipped_prefilter,
            report.targets,
            job.llm_cost_rub,
        )

        if config.auto_send:
            logger.info("Job %s: auto-sending outreach", job_id)
            report = await send_job_outreach(job_id)
            logger.info(
                "Job %s: sent=%d ready=%d failed=%d",
                job_id,
                report.sent,
                report.ready_manual,
                report.failed,
            )

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        await db.update_job(job)


async def _save_skipped_lead(raw, job_id: str, reason: str) -> None:
    result = AgentResult(
        fit_score=0,
        is_target=False,
        reason=reason,
        pains=[],
        hook="",
        product_angle="",
        subject=None,
        message=None,
        channel_hint="email",
        reasoning_summary="Отсечено prefilter без LLM",
        website_issues=[],
    )
    lead_record = LeadRecord(
        job_id=job_id,
        raw=raw,
        result=result,
        trace=[
            AgentTraceStep(round=0, type="prefilter", content=reason),
        ],
        llm_cost_rub=0.0,
    )
    await db.save_lead(lead_record)


async def process_lead(
    agent: ScoutAgent,
    raw,
    config: ICPConfig,
    job_id: str,
    *,
    use_lite: bool = False,
) -> ProcessedLead:
    enriched_raw, website_audit, preflight_trace, contacts, website_content = (
        await enrich_lead_with_website_audit(raw, lite=use_lite)
    )

    if use_lite:
        processed = await agent.process_lead_lite(
            lead=enriched_raw,
            icp=config.icp,
            product=config.product,
            tone=config.tone,
            website_audit=website_audit,
            preflight_trace=preflight_trace,
            contacts=contacts,
            website_content=website_content,
        )
    else:
        processed = await agent.process_lead(
            lead=enriched_raw,
            icp=config.icp,
            product=config.product,
            tone=config.tone,
            website_audit=website_audit,
            preflight_trace=preflight_trace,
            contacts=contacts,
        )

    email = pick_email(contacts, enriched_raw)
    result_updates: dict = {}
    if contacts.lpr_name:
        result_updates["lpr_name"] = contacts.lpr_name
    if processed.result and processed.result.is_target and contacts.best_channel:
        result_updates["channel_hint"] = contacts.best_channel
    if processed.result and result_updates:
        processed.result = processed.result.model_copy(update=result_updates)

    settings = get_settings()
    followups = []
    followup_cost = 0.0
    min_fu_score = settings.followup_min_fit_score
    if (
        config.generate_followups
        and processed.result
        and processed.result.is_target
        and processed.result.message
        and processed.result.fit_score >= min_fu_score
    ):
        lead_stub = LeadRecord(
            job_id=job_id,
            raw=processed.raw,
            result=processed.result,
            website_audit=website_audit,
        )
        followups, followup_cost = await generate_followups(
            lead_stub,
            product=config.product,
            tone=config.tone,
        )
        processed.llm_cost_rub += followup_cost
        record_llm_cost(followup_cost)

    lead_record = LeadRecord(
        job_id=job_id,
        raw=processed.raw,
        result=processed.result,
        trace=processed.trace,
        website_audit=website_audit,
        email=email,
        contacts=contacts,
        fit_score=processed.result.fit_score if processed.result else None,
        llm_cost_rub=processed.llm_cost_rub,
        followups=followups,
        send_status=SendStatus.PENDING if processed.result and processed.result.is_target else None,
    )
    lead_record = await prepare_outreach_channels(lead_record)
    await db.save_lead(lead_record)

    if processed.result and processed.result.is_target:
        try:
            settings = get_settings()
            if settings.department_enabled:
                from scout.department.agents.sales import SalesAgent

                sales = SalesAgent()
                await sales.create_deal_from_lead(
                    lead_record.id,
                    processed.raw.name,
                    email,
                    processed.raw.phone,
                )
        except Exception:
            logger.exception("Failed to create deal for lead %s", lead_record.id)

    return processed


def pick_email(contacts: LeadContacts, raw) -> str | None:
    if contacts.emails:
        return contacts.emails[0]
    return raw.email
