from __future__ import annotations

import logging

from office.crews.loader import get_preset, load_presets
from office.models import AgentStatus, WorkstationRecord
from office.storage import db as office_db

logger = logging.getLogger(__name__)


async def create_workstation_from_preset(
    preset_id: str,
    *,
    name: str | None = None,
    custom_prompt: str = "",
) -> WorkstationRecord:
    preset = get_preset(preset_id)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_id}")
    ws = WorkstationRecord(
        name=name or preset.role,
        preset_id=preset_id,
        department_slug=preset.department,
        role=preset.role,
        model_tier=preset.model_tier,
        custom_prompt=custom_prompt,
        skills=list(preset.skills),
        status=AgentStatus.IDLE,
    )
    return await office_db.save_workstation(ws)


async def seed_default_heads() -> list[WorkstationRecord]:
    """Ensure department head workstations exist."""
    created: list[WorkstationRecord] = []
    existing = {w.preset_id for w in await office_db.list_workstations()}
    for preset_id, preset in load_presets().items():
        if not preset.is_head or preset_id in existing:
            continue
        ws = await create_workstation_from_preset(preset_id)
        created.append(ws)
    return created


async def seed_default_assistants() -> list[WorkstationRecord]:
    """Ensure default CEO assistants exist (secretary, etc.)."""
    created: list[WorkstationRecord] = []
    existing = {w.preset_id for w in await office_db.list_workstations()}
    for preset_id in ("executive_assistant",):
        if preset_id in existing:
            continue
        if not get_preset(preset_id):
            continue
        ws = await create_workstation_from_preset(
            preset_id,
            name="Алина",
            custom_prompt=(
                "Приоритет: мероприятия для B2B SMB в РФ (Юг, вся РФ). "
                "Форматы: вебинары, мастер-классы, отраслевые конференции по digital, "
                "продажам, e-commerce, 1С, автоматизации."
            ),
        )
        created.append(ws)
    return created


def registry_summary() -> dict:
    from office.models import ModelTier

    presets = load_presets()
    return {
        "total_presets": len(presets),
        "departments": sorted({p.department for p in presets.values()}),
        "heads": [p.id for p in presets.values() if p.is_head],
        "execution": [p.id for p in presets.values() if p.model_tier == ModelTier.EXECUTION],
    }
