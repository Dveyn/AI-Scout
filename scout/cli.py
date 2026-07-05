from __future__ import annotations

import argparse
import asyncio
import json
import sys

from scout.agent.runner import process_job, process_lead
from scout.agent.enrichment import enrich_lead_with_website_audit
from scout.agent.scout_agent import ScoutAgent
from scout.collectors.factory import collector_label, get_maps_collector
from scout.config import get_settings
from scout.company import DEFAULT_ICP, DEFAULT_OFFER, DEFAULT_PRODUCT
from scout.models.schemas import ICPConfig, JobCreate, Tone
from scout.autopilot.runner import run_autopilot_campaign, run_daily, run_due_followups
from scout.department.orchestrator import run_daily as run_department_daily
from scout.inbox.imap_checker import check_inbox_and_notify
from scout.outreach.service import build_job_report, send_job_outreach
from scout.presets.loader import load_preset, list_presets
from scout.storage import db


def _resolve_campaign_args(args: argparse.Namespace) -> dict:
    settings = get_settings()
    data = {
        "icp": args.icp or settings.default_icp or DEFAULT_ICP,
        "product": args.product or settings.default_product or DEFAULT_PRODUCT,
        "offer": args.offer or settings.default_offer or DEFAULT_OFFER,
        "query": args.query,
        "city": args.city,
        "limit": args.limit,
        "tone": args.tone,
        "agent_skill": settings.agent_skill,
        "preset": None,
        "generate_followups": settings.generate_followups,
    }
    if getattr(args, "preset", None):
        preset = load_preset(args.preset)
        data["preset"] = args.preset
        for key in (
            "icp",
            "product",
            "offer",
            "query",
            "city",
            "limit",
            "tone",
            "skill",
            "generate_followups",
        ):
            if key in preset and preset[key] is not None:
                if key == "skill":
                    data["agent_skill"] = preset["skill"]
                else:
                    data[key] = preset[key]
        if args.query:
            data["query"] = args.query
        if args.city:
            data["city"] = args.city
        if args.offer:
            data["offer"] = args.offer
    return data


def _print_report(report) -> None:
    print("\n=== Отчёт ===")
    print(f"Собрано:      {report.collected}")
    print(f"Email найден: {report.email_found}")
    print(f"Target:       {report.targets}")
    print(f"Отправлено:   {report.sent}")
    print(f"К ручной:     {report.ready_manual}")
    print(f"Нет контакта: {report.no_contact}")
    print(f"Дубли:        {report.duplicate}")
    print(f"Ошибки:       {report.failed}")
    print(f"Пропущено:    {report.skipped}")


async def cmd_run(args: argparse.Namespace) -> None:
    await db.init_db()
    settings = get_settings()
    if not settings.gptunnel_api_key:
        print("Ошибка: задайте GPTUNNEL_API_KEY в scout/.env", file=sys.stderr)
        sys.exit(1)

    config = ICPConfig(
        icp=args.icp,
        product=args.product,
        offer=args.offer,
        query=args.query,
        city=args.city,
        limit=args.limit,
        tone=Tone(args.tone),
        agent_skill=get_settings().agent_skill,
    )

    print(f"Сбор ({collector_label()}): {config.query} / {config.city} (лимит {config.limit})…")
    scanned_keys = await db.list_scanned_company_keys()
    collector = get_maps_collector()
    leads = await collector.collect(
        config.query,
        config.city,
        config.limit,
        exclude_keys=scanned_keys,
    )
    print(f"Собрано {len(leads)} новых организаций (уже просканированные пропущены)")

    agent = ScoutAgent(skill_name=config.agent_skill)
    for i, raw in enumerate(leads, 1):
        print(f"\n--- Лид {i}/{len(leads)}: {raw.name} ---")
        enriched, audit, trace, contacts, _wc = await enrich_lead_with_website_audit(raw)
        processed = await agent.process_lead(
            lead=enriched,
            icp=config.icp,
            product=config.product,
            tone=config.tone,
            website_audit=audit,
            preflight_trace=trace,
            contacts=contacts,
        )
        print(f"Fit: {processed.result.fit_score} | Target: {processed.result.is_target}")
        if processed.raw.email:
            print(f"Email: {processed.raw.email}")
        print(f"Reason: {processed.result.reason}")
        if processed.result.message:
            print(f"Subject: {processed.result.subject}")
            print(f"Message:\n{processed.result.message}")
        if args.show_trace:
            print("Trace:")
            print(json.dumps([t.model_dump() for t in processed.trace], ensure_ascii=False, indent=2))
        print(f"LLM cost: {processed.llm_cost_rub:.4f} ₽")


async def cmd_blast(args: argparse.Namespace) -> None:
    await db.init_db()
    settings = get_settings()
    if not settings.gptunnel_api_key:
        print("Ошибка: задайте GPTUNNEL_API_KEY в scout/.env", file=sys.stderr)
        sys.exit(1)

    camp = _resolve_campaign_args(args)
    if not camp.get("query") or not camp.get("city"):
        print("Укажите --query и --city (или используйте --preset webstroke)", file=sys.stderr)
        sys.exit(1)

    job = await db.create_job(
        JobCreate(
            icp=camp["icp"],
            product=camp["product"],
            offer=camp["offer"],
            query=camp["query"],
            city=camp["city"],
            limit=int(camp["limit"]),
            tone=Tone(camp["tone"]),
            auto_send=args.send,
            agent_skill=camp.get("agent_skill"),
            preset=camp.get("preset"),
            generate_followups=bool(camp.get("generate_followups", True)),
        )
    )
    print(f"Кампания {job.id}")
    print(f"Запрос: {camp['query']} / {camp['city']}, лимит {camp['limit']}")
    print(f"Skill: {camp.get('agent_skill')} | Пресет: {camp.get('preset')}")
    if args.send:
        print("Режим: собрать → проанализировать → отправить email")

    await process_job(job.id)
    job = await db.get_job(job.id)
    if job and job.status.value == "failed":
        print(f"Ошибка: {job.error}", file=sys.stderr)
        sys.exit(1)

    report = await build_job_report(job.id)
    _print_report(report)
    print(f"\nДашборд: http://localhost:8080/dashboard")
    print(f"Кампания: http://localhost:8080/jobs/{job.id}")


async def cmd_send(args: argparse.Namespace) -> None:
    await db.init_db()
    if not args.job_id:
        print("Укажите --job-id", file=sys.stderr)
        sys.exit(1)

    touch = getattr(args, "touch", 1) or 1
    report = await send_job_outreach(args.job_id, force=args.force, touch=touch)
    _print_report(report)
    if touch > 1:
        print(f"\nОтправлено касание #{touch}")


async def cmd_presets(_: argparse.Namespace) -> None:
    for name in list_presets():
        preset = load_preset(name)
        label = preset.get("label") or name
        print(f"  {label:24} query={preset.get('query')} / {preset.get('city')}")


async def cmd_inbox(_: argparse.Namespace) -> None:
    await db.init_db()
    matched = await check_inbox_and_notify()
    print(f"Ответов от известных лидов: {len(matched)}")
    for m in matched:
        print(f"  {m.get('company_name')} <{m.get('from')}> — {m.get('subject')}")


async def cmd_autopilot(args: argparse.Namespace) -> None:
    await db.init_db()
    settings = get_settings()
    if not settings.gptunnel_api_key:
        print("Ошибка: задайте GPTUNNEL_API_KEY в scout/.env", file=sys.stderr)
        sys.exit(1)

    sub = args.autopilot_command
    if sub == "daily":
        result = await run_daily(force=args.force)
        fu = result["followups"]
        print(f"Follow-up: проверено {fu['checked']}, отправлено {fu['sent']}, пропущено {fu['skipped']}")
        report = result["campaign"]
        if report:
            _print_report(report)
        else:
            print("Кампания не запущена (лимит дня или autopilot выключен)")
        return

    if sub == "followups":
        stats = await run_due_followups(dry_run=args.dry_run)
        print(
            f"Follow-up: проверено {stats['checked']}, отправлено {stats['sent']}, "
            f"пропущено {stats['skipped']}, ошибок {stats['failed']}"
        )
        return

    # run — одна кампания из очереди
    report = await run_autopilot_campaign(force=args.force)
    if not report:
        print("Кампания не запущена. Включите AUTOPILOT_ENABLED=true или используйте --force")
        sys.exit(0)
    _print_report(report)


async def cmd_department(args: argparse.Namespace) -> None:
    await db.init_db()
    settings = get_settings()
    if not settings.gptunnel_api_key:
        print("Ошибка: задайте GPTUNNEL_API_KEY в scout/.env", file=sys.stderr)
        sys.exit(1)

    sub = args.department_command
    if sub == "daily":
        result = await run_department_daily(force=args.force)
        print(f"Mode: {result.get('mode', '?')}")
        print(f"Inbox replies: {result.get('inbox_replies', 0)}")
        print(f"Tasks created: {result.get('tasks_created', 0)}")
        print(f"Cursor handoffs: {result.get('cursor_handoffs', 0)}")
        print(f"Cursor outputs: {result.get('cursor_outputs', {})}")
        print(f"Verdicts applied: {result.get('verdicts_applied', 0)}")
        stats = result.get("task_stats") or {}
        print(f"SMM/SEO/Ads: {stats}")
        if result.get("report"):
            r = result["report"]
            print(f"Report {r.report_date}: {r.summary[:200]}")
        return

    if sub == "approve-task":
        from scout.storage import department_db as dept_db

        await dept_db.approve_task(args.task_id)
        print(f"Task {args.task_id} approved")
        return

    if sub == "approve-ad":
        from scout.department.models import AdCreativeStatus
        from scout.storage import department_db as dept_db

        await dept_db.update_ad_creative_status(args.creative_id, AdCreativeStatus.APPROVED)
        print(f"Ad creative {args.creative_id} approved")


async def cmd_reset(args: argparse.Namespace) -> None:
    await db.init_db()
    if not args.yes:
        print(
            "Будут удалены все кампании, лиды, реестр просканированных компаний "
            "и история отправок.",
            file=sys.stderr,
        )
        print("Повторите с флагом --yes", file=sys.stderr)
        sys.exit(1)
    counts = await db.clear_all_data()
    print("База очищена:")
    for table, count in counts.items():
        print(f"  {table}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Scout CLI")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Собрать лиды и прогнать через агента (без БД job)")
    run.add_argument("--query", required=True)
    run.add_argument("--city", required=True)
    run.add_argument("--limit", type=int, default=5)
    run.add_argument("--icp", default="Локальный B2B-бизнес с сайтом, которому нужен маркетинг")
    run.add_argument("--product", default="Услуги digital-маркетинга и лидогенерации")
    run.add_argument("--offer", default=None, help="Короткое предложение для письма")
    run.add_argument("--tone", choices=["business", "friendly"], default="business")
    run.add_argument("--show-trace", action="store_true")
    run.set_defaults(func=cmd_run)

    blast = sub.add_parser("blast", help="Полный цикл: сбор → агент → (опционально) отправка")
    blast.add_argument("--query", default=None)
    blast.add_argument("--city", default=None)
    blast.add_argument("--limit", type=int, default=10)
    blast.add_argument("--icp", default=None)
    blast.add_argument("--product", default=None)
    blast.add_argument("--offer", default=None, help="Текст предложения")
    blast.add_argument("--tone", choices=["business", "friendly"], default="business")
    blast.add_argument("--preset", default="webstroke", help="Пресет кампании (scout/presets/)")
    blast.add_argument("--send", action="store_true", help="Отправить email после обработки")
    blast.set_defaults(func=cmd_blast)

    send = sub.add_parser("send", help="Отправить письма по готовой кампании")
    send.add_argument("--job-id", required=True)
    send.add_argument("--touch", type=int, default=1, help="Номер касания (1–3)")
    send.add_argument("--force", action="store_true", help="Отправить повторно, игнорируя дубли")
    send.set_defaults(func=cmd_send)

    presets = sub.add_parser("presets", help="Список пресетов кампаний")
    presets.set_defaults(func=cmd_presets)

    autopilot = sub.add_parser("autopilot", help="Автопилот: очередь кампаний и follow-up")
    ap_sub = autopilot.add_subparsers(dest="autopilot_command", required=True)

    ap_run = ap_sub.add_parser("run", help="Следующая кампания из очереди")
    ap_run.add_argument("--force", action="store_true", help="Игнорировать AUTOPILOT_ENABLED и лимит дня")
    ap_run.set_defaults(func=cmd_autopilot)

    ap_daily = ap_sub.add_parser("daily", help="Follow-up + кампания (для cron)")
    ap_daily.add_argument("--force", action="store_true")
    ap_daily.set_defaults(func=cmd_autopilot)

    ap_fu = ap_sub.add_parser("followups", help="Отправить просроченные follow-up")
    ap_fu.add_argument("--dry-run", action="store_true", help="Только показать, кому пора")
    ap_fu.set_defaults(func=cmd_autopilot)

    inbox = sub.add_parser("inbox", help="Проверить IMAP на ответы от лидов")
    inbox.set_defaults(func=cmd_inbox)

    department = sub.add_parser("department", help="AI Marketing Department")
    dept_sub = department.add_subparsers(dest="department_command", required=True)

    dept_daily = dept_sub.add_parser("daily", help="Полный цикл отдела (для cron)")
    dept_daily.add_argument("--force", action="store_true")
    dept_daily.set_defaults(func=cmd_department)

    dept_approve = dept_sub.add_parser("approve-task", help="Утвердить задачу CMO")
    dept_approve.add_argument("--task-id", required=True)
    dept_approve.set_defaults(func=cmd_department)

    dept_ad = dept_sub.add_parser("approve-ad", help="Утвердить рекламный креатив")
    dept_ad.add_argument("--creative-id", required=True)
    dept_ad.set_defaults(func=cmd_department)

    reset = sub.add_parser("reset", help="Очистить все кампании и анализы")
    reset.add_argument("--yes", action="store_true", help="Подтвердить удаление")
    reset.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
