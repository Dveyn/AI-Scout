from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scout.config import SCOUT_ROOT

STATE_PATH = SCOUT_ROOT / "data" / "daily_state.json"


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _hour_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H")


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


def _reset_if_needed(state: dict) -> dict:
    today = _today()
    if state.get("date") != today:
        state["date"] = today
        state["llm_cost_rub"] = 0.0
        state["emails_sent"] = 0
        state["domain_counts"] = {}
    hour = _hour_key()
    if state.get("hour") != hour:
        state["hour"] = hour
        state["emails_sent_this_hour"] = 0
    return state


def get_state() -> dict:
    return _reset_if_needed(_load())


def add_llm_cost(amount: float) -> float:
    state = get_state()
    state["llm_cost_rub"] = round(float(state.get("llm_cost_rub", 0)) + amount, 4)
    _save(state)
    return state["llm_cost_rub"]


def llm_spent_today() -> float:
    return float(get_state().get("llm_cost_rub", 0))


def record_email_sent(email: str) -> None:
    state = get_state()
    state["emails_sent"] = int(state.get("emails_sent", 0)) + 1
    state["emails_sent_this_hour"] = int(state.get("emails_sent_this_hour", 0)) + 1
    domain = email.split("@", 1)[-1].lower() if "@" in email else ""
    if domain:
        counts = state.setdefault("domain_counts", {})
        counts[domain] = int(counts.get(domain, 0)) + 1
    _save(state)


def emails_sent_today() -> int:
    return int(get_state().get("emails_sent", 0))


def emails_sent_this_hour() -> int:
    return int(get_state().get("emails_sent_this_hour", 0))


def domain_sent_today(domain: str) -> int:
    counts = get_state().get("domain_counts") or {}
    return int(counts.get(domain.lower(), 0))
