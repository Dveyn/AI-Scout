from __future__ import annotations

from pathlib import Path

import yaml

PRESETS_DIR = Path(__file__).resolve().parent


def list_presets() -> list[str]:
    return sorted(p.stem for p in PRESETS_DIR.glob("*.yaml"))


def load_preset(name: str) -> dict:
    path = PRESETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Пресет не найден: {name}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Некорректный пресет: {name}")
    return data
