from __future__ import annotations

import logging

from scout.tools.audit_value import enrich_audit_with_business_value, merge_audits
from scout.tools.indexlift_audit import adapt_indexlift_audit, run_indexlift_audit
from scout.tools.website_audit import audit_website

logger = logging.getLogger(__name__)


async def audit_website_full(url: str, *, run_seo: bool | None = None) -> dict:
    """Python-аудит + IndexLift SEO только если сайт слабый (экономия)."""
    from scout.config import get_settings

    settings = get_settings()
    base = await audit_website(url)
    issues = base.get("issues") or []
    score = int(base.get("quality_score") or 100)

    should_seo = run_seo if run_seo is not None else (
        settings.indexlift_enabled
        and (
            score < settings.indexlift_only_below_score
            or len(issues) >= settings.indexlift_min_issues
        )
    )

    if not should_seo:
        return enrich_audit_with_business_value(base)

    try:
        raw_seo = await run_indexlift_audit(url)
        if raw_seo:
            seo = adapt_indexlift_audit(raw_seo)
            return merge_audits(base, seo)
    except Exception as exc:
        logger.warning("IndexLift skipped for %s: %s", url, exc)
    return enrich_audit_with_business_value(base)
