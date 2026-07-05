from __future__ import annotations

from pathlib import Path

import yaml

from office.models import ModelTier, PresetDefinition

PRESETS_PATH = Path(__file__).resolve().parent / "presets" / "webstudio.yaml"

_cache: dict[str, PresetDefinition] | None = None
_heads: dict[str, str] | None = None


def _load_yaml() -> dict:
    with PRESETS_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_presets() -> dict[str, PresetDefinition]:
    global _cache
    if _cache is not None:
        return _cache
    data = _load_yaml()
    presets: dict[str, PresetDefinition] = {}
    for preset_id, raw in (data.get("presets") or {}).items():
        presets[preset_id] = PresetDefinition(
            id=preset_id,
            role=raw["role"],
            department=raw["department"],
            model_tier=ModelTier(raw.get("model_tier", "execution")),
            skills=list(raw.get("skills") or []),
            tools=list(raw.get("tools") or []),
            backstory=raw.get("backstory", ""),
            is_head=bool(raw.get("is_head", False)),
        )
    _cache = presets
    return presets


def get_preset(preset_id: str) -> PresetDefinition | None:
    return load_presets().get(preset_id)


def list_presets_for_department(department: str) -> list[PresetDefinition]:
    return [p for p in load_presets().values() if p.department == department]


def department_heads() -> dict[str, str]:
    global _heads
    if _heads is not None:
        return _heads
    data = _load_yaml()
    raw = data.get("department_heads") or {}
    if isinstance(raw, list):
        merged: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict):
                merged.update(item)
        _heads = merged
    else:
        _heads = dict(raw)
    return _heads


def head_preset_for_department(department_slug: str) -> PresetDefinition | None:
    preset_id = department_heads().get(department_slug)
    return get_preset(preset_id) if preset_id else None
