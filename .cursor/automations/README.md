# Cursor Automations for AI Marketing Department

## Экономия: что где работает

| Задача | Где | Платите |
|--------|-----|---------|
| Лиды + персональные письма (Scout) | Локально GPTunnel | GPTunnel ₽ |
| KPI из SQLite | Локально | **бесплатно** |
| CMO, Analytics, SMM, SEO, Ads | **Cursor Automations** | подписка Cursor |
| Ответы на входящие | Cursor (`sales-reply-assist`) | Cursor |
| Публикация VK/TG/файлы SEO | Локально после verdicts | **бесплатно** |

В `scout/.env` установите:
```env
DEPARTMENT_LLM_PROVIDER=cursor
SCOUT_OUTREACH_LLM_ENABLED=true   # только аутрич жрёт GPTunnel
LLM_DAILY_BUDGET_RUB=30           # лимит на письма
INDEXLIFT_ENABLED=false           # в тесте отключить SEO-аудит на GPTunnel
```

## Setup checklist

1. **GitHub** — Cursor Settings → Integrations → connect repo
2. **Cloud Agent env** — `.cursor/environment.json` runs `make install`
3. **Webhooks** — after saving automations, copy to `scout/.env`:
   - `CURSOR_WEBHOOK_DEPARTMENT_DAILY` ← главный (CMO+контент)
   - `CURSOR_WEBHOOK_ADS_APPROVAL`
   - `CURSOR_WEBHOOK_SALES_REPLY`
   - `CURSOR_WEBHOOK_API_KEY`

## Creating automations

Agents Window → `/automate` → import YAML from this folder.

Priority automations:
1. **office-directive.yaml** — **CEO задача → COO → готовый результат** (AI Office)
2. **department-daily.yaml** — webhook, ежедневный маркетинг
3. **sales-reply-assist.yaml** — входящие ответы
4. **ads-approval-gate.yaml** — реклама

## CEO task (AI Office)

```bash
make office-task BRIEF="ваша задача"
make office-ingest
```

См. [office/QUICKSTART.md](../office/QUICKSTART.md)

Webhooks в `scout/.env`:
- `CURSOR_WEBHOOK_OFFICE_DIRECTIVE` ← office-directive.yaml
- `CURSOR_WEBHOOK_DEPARTMENT_DAILY` ← department-daily.yaml (fallback)

## Handoff / verdict flow

```
Scout (бесплатно)                    Cursor (подписка)
─────────────────                    ─────────────────
pending/daily-cycle-*.json    →      Cloud Agent
pending/sales-reply-*.json    →      generates content
                                     ↓
                             verdicts/cmo-plan-*.json
                             verdicts/content-*.json
                             verdicts/analytics-*.json
                                     ↓
Scout ingests + publishes     ←      next department daily
```

Folders under `scout/data/cursor/`:
- `pending/` — задачи для Cursor
- `reports/` — markdown KPI для человека
- `verdicts/` — ответы Cursor (Scout читает при следующем цикле)
- `done/` — обработано

## Verdict JSON schemas

See prompts in `department-daily.yaml`.
