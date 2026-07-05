# AI Scout

B2B lead generation: Yandex Maps → site analysis → personalized email outreach.

## Quick start

```bash
cd scout
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# GPTUNNEL_API_KEY + SMTP (для отправки)
```

Run web UI (from repo root):

```bash
make run
# http://localhost:8080
# http://localhost:8080/dashboard — статистика и история отправок
```

## CLI

Полный цикл (сбор → агент → отчёт):

```bash
make blast QUERY="стоматология" CITY="Москва" LIMIT=10 OFFER="Аудит сайта бесплатно"
```

С автоотправкой email:

```bash
make blast QUERY="стоматология" CITY="Москва" SEND=1
```

Отправить по готовой кампании:

```bash
make send JOB_ID=uuid-...
```

## Pipeline

1. **Collector** — Playwright: компании с Яндекс.Карт + email с карточки
2. **Enrichment** — сайт с карточки, аудит, email с сайта (/contacts и т.д.)
3. **ScoutAgent** — анализ сайта/отзывов, персональное письмо (не спам)
4. **Outreach** — SMTP-отправка, дедуп, WhatsApp fallback если нет email
5. **Dashboard** — кому, куда, когда, статус, история за всё время

## Config (.env)

| Variable | Description |
|----------|-------------|
| `GPTUNNEL_API_KEY` | API key GPTunnel |
| `SMTP_*` | SMTP для отправки писем |
| `AUTO_SEND_EMAIL` | Отправлять сразу после кампании |
| `DEFAULT_OFFER` | Текст предложения для CLI |
| `FIT_SCORE_THRESHOLD` | Мин. score для письма (default 60) |

## Legal notice

- Scraping Yandex Maps may violate their Terms of Service; use for small pilots only
- Comply with 152-FZ when storing personal data (phones, names)
- Do not send bulk spam; manually review messages before outreach
- For production scale, consider official Yandex Organization Search API

## Документация

- **[SETUP.md](SETUP.md)** — полный гайд с нуля (установка, сервер, cron, почта)
- [DEPLOY.md](DEPLOY.md) — PM2 и файрвол

## Автопилот (кратко)

Подробно: [SETUP.md](SETUP.md#7-автопилот-cron).

```bash
make autopilot-daily    # IMAP → follow-up → кампания → Telegram
```

**Cron обязателен** — без него кампании сами не запустятся.

## Sales pitch (first 3–5 clients)

**Opening:** «Я собрал AI-систему, которая находит идеальных клиентов на Яндекс.Картах и пишет им персональные сообщения — не шаблонный спам, а текст с конкретикой по их бизнесу.»

**Lead magnet:** «Опишите вашего идеального клиента. Я бесплатно прогоню 10 компаний через систему и пришлю готовые письма — сами оцените качество.»

**Close:** «Тест-драйв: за 15 000–25 000 ₽ система находит 200 целевых контактов, пишет под каждого личное сообщение и отдаёт CSV. Вам остаётся отвечать тем, кто согласился на созвон.»

**Demo tip:** Expand «Как думал агент» in the UI — show which tools were called and why. This sells the «custom AI» story.

## Example ICP

```
Стоматологии и стоматологические клиники в крупных городах.
Рейтинг 4.0+, есть сайт, 50+ отзывов.
Им нужны новые пациенты, но слабый digital-маркетинг.
```

Product: «Контекстная реклама и лидогенерация для медклиник»
