from __future__ import annotations

from pathlib import Path

from office.crews.loader import get_preset
from office.models import WorkstationRecord

SKILLS_ROOT = Path.home() / ".agents" / "skills"


def load_skill_text(skill_name: str) -> str:
    path = SKILLS_ROOT / skill_name / "SKILL.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")[:4000]
    return ""


def build_agent_system_prompt(ws: WorkstationRecord) -> str:
    preset = get_preset(ws.preset_id) if ws.preset_id else None
    parts: list[str] = []
    if preset:
        parts.append(f"Ты — {preset.role} в веб-студии ВебШтрих.")
        if preset.backstory:
            parts.append(preset.backstory)
    else:
        parts.append(f"Ты — {ws.role} в веб-студии ВебШтрих.")
    if ws.custom_prompt.strip():
        parts.append(ws.custom_prompt.strip())
    skills = ws.skills or (preset.skills if preset else [])
    for skill in skills[:4]:
        text = load_skill_text(skill)
        if text:
            parts.append(f"\n## Skill: {skill}\n{text[:2000]}")
    return "\n\n".join(parts)
