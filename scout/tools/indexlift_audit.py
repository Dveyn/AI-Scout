from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from scout.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_SKILL_PATH = Path.home() / ".agents/skills/indexlift-seo-auditor"


async def run_indexlift_audit(url: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.indexlift_enabled:
        return None

    skill_path = Path(settings.indexlift_skill_path) if settings.indexlift_skill_path else DEFAULT_SKILL_PATH
    script = skill_path / "scripts" / "run-audit.js"
    if not script.is_file():
        logger.warning("IndexLift not found at %s", skill_path)
        return None

    with tempfile.TemporaryDirectory(prefix="scout-seo-") as tmp:
        out = Path(tmp)
        cmd = [
            "node",
            str(script),
            "--url",
            url,
            "--mode",
            settings.indexlift_mode,
            "--tier",
            settings.indexlift_tier,
            "--engines",
            settings.indexlift_engines,
            "--format",
            "json",
            "--output",
            str(out),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(skill_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=settings.indexlift_timeout_sec,
            )
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("IndexLift timeout for %s", url)
            return None

        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace")[:300]
            logger.warning("IndexLift failed for %s: %s", url, err)
            return None

        json_files = sorted(out.glob("*.json"))
        if not json_files:
            return None
        try:
            return json.loads(json_files[0].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def adapt_indexlift_audit(raw: dict[str, Any]) -> dict[str, Any]:
    summary = raw.get("summary") or {}
    scores = raw.get("scores") or {}
    overall = scores.get("overall") or {}
    score = summary.get("score") or overall.get("score") or 50

    findings = raw.get("findings") or []
    priority: list[dict[str, Any]] = []
    for finding in findings:
        status = finding.get("status")
        if status not in ("FAIL", "WARN"):
            continue
        title = finding.get("title") or ""
        if not title:
            continue
        engines = finding.get("engines") or []
        prefix = ""
        if engines == ["yandex"] or (engines and "yandex" in engines and "google" not in engines):
            prefix = "[Яндекс] "
        elif engines:
            prefix = "[SEO] "
        rec = (finding.get("recommendation") or finding.get("details") or "").strip()
        text = f"{prefix}{title}"
        if rec and len(rec) <= 140:
            text = f"{text} — {rec}"
        priority.append(
            {
                "id": finding.get("id"),
                "status": status,
                "severity": finding.get("severity", "medium"),
                "category": finding.get("category"),
                "engines": engines,
                "text": text,
            }
        )

    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    priority.sort(key=lambda item: sev_order.get(str(item.get("severity", "medium")), 2))
    issues = [p["text"] for p in priority[:8]]

    business_layer = raw.get("business_priority") or {}
    business_hooks: list[str] = []
    for item in (business_layer.get("top_priorities") or business_layer.get("items") or [])[:3]:
        if isinstance(item, str):
            business_hooks.append(item)
        elif isinstance(item, dict):
            hook = item.get("title") or item.get("recommendation") or item.get("details")
            if hook:
                business_hooks.append(str(hook))

    return {
        "source": "indexlift",
        "url": (raw.get("metadata") or {}).get("url"),
        "quality_score": int(score),
        "grade": summary.get("grade"),
        "issues": issues,
        "indexlift_findings": priority[:12],
        "business_hooks": business_hooks,
        "yandex_score": (scores.get("yandex") or {}).get("score"),
        "technical_score": (scores.get("technical") or {}).get("score"),
        "onpage_score": (scores.get("onpage") or {}).get("score"),
        "failures": summary.get("failures"),
        "warnings": summary.get("warnings"),
    }
