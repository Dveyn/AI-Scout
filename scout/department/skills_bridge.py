"""Load marketing skills from ~/.agents/skills for department agents."""

from __future__ import annotations

from pathlib import Path

from scout.agent.skills.loader import load_product_marketing

SKILLS_HOME = Path.home() / ".agents" / "skills"
PROJECT_AGENTS = Path(__file__).resolve().parents[2] / ".agents"

AGENT_SKILL_MAP: dict[str, list[str]] = {
    "cmo": ["marketing-plan", "competitors", "product-marketing", "analytics"],
    "sales": ["prospecting", "cold-email", "sales-enablement"],
    "smm": ["content-strategy", "copywriting", "social", "video"],
    "ads": ["ads", "ad-creative", "ab-testing", "cro"],
    "seo": ["seo-audit", "ai-seo", "programmatic-seo", "indexlift-seo-auditor"],
    "analytics": ["analytics", "observability-and-instrumentation"],
}


def _read_skill(name: str, max_chars: int = 12000) -> str:
    path = SKILLS_HOME / name / "SKILL.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[... truncated ...]"
    return text


def load_department_skill(agent_name: str) -> str:
    """Combine product marketing context + agent-specific skills."""
    parts: list[str] = []

    pm = load_product_marketing()
    if not pm and (PROJECT_AGENTS / "product-marketing.md").is_file():
        pm = (PROJECT_AGENTS / "product-marketing.md").read_text(encoding="utf-8").strip()
    if pm:
        parts.append(f"# Product Marketing Context\n\n{pm}")

    for skill_name in AGENT_SKILL_MAP.get(agent_name, []):
        content = _read_skill(skill_name)
        if content:
            parts.append(f"# Skill: {skill_name}\n\n{content}")

    if agent_name == "sales":
        outreach = Path(__file__).resolve().parents[1] / "agent" / "skills" / "outreach-writer" / "SKILL.md"
        if outreach.is_file():
            parts.append(f"# Outreach Writer\n\n{outreach.read_text(encoding='utf-8')[:8000]}")

    return "\n\n---\n\n".join(parts)
