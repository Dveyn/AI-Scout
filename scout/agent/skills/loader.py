"""Загрузка skills для ScoutAgent."""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).parent
SCOUT_ROOT = SKILLS_DIR.parents[1]
PROJECT_ROOT = SKILLS_DIR.parents[2]

PRODUCT_MARKETING_CANDIDATES = (
    PROJECT_ROOT / ".agents" / "product-marketing.md",
    SCOUT_ROOT / ".agents" / "product-marketing.md",
    Path.home() / ".agents" / "product-marketing.md",
)

OUTREACH_BASE_FILES = ("SKILL.md", "persuasion.md", "examples.md")
NICHE_SKILLS = frozenset({
    "outreach-production",
    "outreach-opt",
    "outreach-logistics",
    "outreach-food-delivery",
})


def load_product_marketing() -> str:
    for path in PRODUCT_MARKETING_CANDIDATES:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def _read_skill_files(skill_dir: Path, files: tuple[str, ...]) -> list[str]:
    parts: list[str] = []
    for name in files:
        path = skill_dir / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return parts


def load_skill(name: str, *, include_examples: bool = True) -> str:
    """Load skill markdown for injection into system prompt."""
    parts: list[str] = []

    if name != "followup-writer":
        pm = load_product_marketing()
        if pm:
            parts.append(f"# Product Marketing Context\n\n{pm}")

    if name in NICHE_SKILLS:
        base_dir = SKILLS_DIR / "outreach-writer"
        base_files = ("SKILL.md", "persuasion.md")
        if include_examples:
            base_files = OUTREACH_BASE_FILES
        parts.extend(_read_skill_files(base_dir, base_files))
        parts.append("---\n\n# Нишевый слой\n")
        niche_dir = SKILLS_DIR / name
        parts.extend(_read_skill_files(niche_dir, ("SKILL.md",)))
        if include_examples:
            parts.extend(_read_skill_files(niche_dir, ("examples.md",)))
    else:
        skill_dir = SKILLS_DIR / name
        if skill_dir.is_dir():
            files = list(OUTREACH_BASE_FILES) if name == "outreach-writer" else ("SKILL.md",)
            if not include_examples and "examples.md" in files:
                files.remove("examples.md")
            parts.extend(_read_skill_files(skill_dir, tuple(files)))

    return "\n\n".join(p for p in parts if p).strip()


def list_skills() -> list[str]:
    return sorted(
        p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    )
