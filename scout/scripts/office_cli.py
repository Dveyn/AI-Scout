#!/usr/bin/env python3
"""Поставить задачу CEO → Cursor Automation → результат в office."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time


async def _submit(brief: str, wait: bool, wait_sec: int) -> int:
    from office.orchestrator.directive_router import ingest_cursor_results, run_directive_smart
    from office.storage import db as office_db
    from office.storage.db import init_db

    await init_db()
    d = await run_directive_smart(brief)
    print(f"ID: {d.id}")
    print(f"Статус: {d.status.value}")

    if d.status.value == "completed" and d.final_report:
        print("\n--- Готовый результат ---\n")
        print(d.final_report)
        return 0

    if d.coo_plan:
        print(f"\n{d.coo_plan}")

    if not wait:
        print(
            "\nКогда Cursor закончит, забрать результат:\n"
            f"  make office-result ID={d.id}\n"
            "или: make office-ingest"
        )
        return 0

    print(f"\nЖду результат до {wait_sec} с (polling)...")
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        await ingest_cursor_results()
        updated = await office_db.get_directive(d.id)
        if updated and updated.status.value == "completed" and updated.final_report:
            print("\n--- Готовый результат ---\n")
            print(updated.final_report)
            return 0
        await asyncio.sleep(8)

    print("\nТаймаут. Cursor ещё работает. Позже: make office-result ID=" + d.id)
    return 1


async def _ingest(directive_id: str | None) -> int:
    from office.orchestrator.directive_router import ingest_cursor_results
    from office.storage import db as office_db
    from office.storage.db import init_db

    await init_db()
    n = await ingest_cursor_results()
    print(f"Импортировано verdicts: {n}")
    if directive_id:
        d = await office_db.get_directive(directive_id)
        if not d:
            print("Директива не найдена", file=sys.stderr)
            return 1
        if d.final_report:
            print("\n--- Готовый результат ---\n")
            print(d.final_report)
            return 0
        print(f"Статус: {d.status.value}")
        if d.coo_plan:
            print(d.coo_plan)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="CEO task → AI Office / Cursor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_task = sub.add_parser("task", help="Отдать задачу начальнику")
    p_task.add_argument("brief", nargs="+", help="Текст задачи")
    p_task.add_argument("--wait", action="store_true", help="Ждать результат")
    p_task.add_argument("--wait-sec", type=int, default=600)

    p_ingest = sub.add_parser("ingest", help="Забрать результаты из cursor/verdicts")
    p_ingest.add_argument("--id", dest="directive_id", default="")

    args = parser.parse_args()
    if args.cmd == "task":
        brief = " ".join(args.brief).strip()
        if len(brief) < 5:
            print("Задача слишком короткая", file=sys.stderr)
            sys.exit(1)
        code = asyncio.run(_submit(brief, args.wait, args.wait_sec))
        sys.exit(code)
    if args.cmd == "ingest":
        code = asyncio.run(_ingest(args.directive_id or None))
        sys.exit(code)


if __name__ == "__main__":
    main()
