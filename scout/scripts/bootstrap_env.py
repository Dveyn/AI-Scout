#!/usr/bin/env python3
"""Создаёт scout/.env и подставляет секреты / серверные дефолты (идемпотентно)."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / "scout" / ".env"
EXAMPLE_PATH = ROOT / "scout" / ".env.example"

SERVER_DEFAULTS: dict[str, str] = {
    "SCOUT_BIND_HOST": "0.0.0.0",
    "SCOUT_REQUIRE_AUTH": "true",
    "DEPARTMENT_ENABLED": "true",
    "DEPARTMENT_TEST_MODE": "false",
    "DEPARTMENT_LOCAL_INTERVAL_MIN": "360",
    "AUTOPILOT_ENABLED": "true",
    "PLAYWRIGHT_HEADLESS": "true",
}

LOCAL_DEFAULTS: dict[str, str] = {
    "SCOUT_BIND_HOST": "127.0.0.1",
    "SCOUT_REQUIRE_AUTH": "false",
    "DEPARTMENT_TEST_MODE": "true",
    "DEPARTMENT_LOCAL_INTERVAL_MIN": "60",
}


def parse_env(text: str) -> tuple[list[str], dict[str, str]]:
    lines: list[str] = []
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, val = stripped.partition("=")
            values[key.strip()] = val.strip()
        lines.append(line)
    return lines, values


def set_key(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) or (
            not stripped.startswith("#") and stripped.startswith(f"{key}=")
        ):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Локальные дефолты (127.0.0.1)")
    parser.add_argument("--force-secrets", action="store_true", help="Перегенерировать пароль и secret key")
    args = parser.parse_args()

    if not EXAMPLE_PATH.is_file():
        print(f"Ошибка: нет {EXAMPLE_PATH}", file=sys.stderr)
        return 1

    if not ENV_PATH.is_file():
        ENV_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Создан {ENV_PATH} из шаблона")

    lines, values = parse_env(ENV_PATH.read_text(encoding="utf-8"))

    defaults = LOCAL_DEFAULTS if args.local else SERVER_DEFAULTS
    for key, val in defaults.items():
        if not values.get(key):
            lines = set_key(lines, key, val)
            values[key] = val

    if args.force_secrets or not values.get("SCOUT_SECRET_KEY"):
        lines = set_key(lines, "SCOUT_SECRET_KEY", secrets.token_hex(32))
    if args.force_secrets or not values.get("SCOUT_AUTH_PASSWORD"):
        lines = set_key(lines, "SCOUT_AUTH_PASSWORD", secrets.token_urlsafe(16))

    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"OK: {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
