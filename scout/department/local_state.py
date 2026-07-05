"""Local/test mode state — throttle CMO to once per day."""

from __future__ import annotations

import json
from datetime import datetime

from scout.config import SCOUT_ROOT, get_settings

STATE_PATH = SCOUT_ROOT / "data" / "department_state.json"


def _load() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_run_cmo_cycle() -> bool:
    """In test mode, Analytics+CMO run at most once per UTC day."""
    if not get_settings().department_test_mode:
        return True
    state = _load()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return state.get("cmo_date") != today


def mark_cmo_cycle_done() -> None:
    state = _load()
    state["cmo_date"] = datetime.utcnow().strftime("%Y-%m-%d")
    state["last_run_at"] = datetime.utcnow().isoformat()
    state["cycles_today"] = int(state.get("cycles_today", 0)) + 1
    _save(state)


def record_scheduler_tick() -> None:
    state = _load()
    state["last_scheduler_at"] = datetime.utcnow().isoformat()
    _save(state)
