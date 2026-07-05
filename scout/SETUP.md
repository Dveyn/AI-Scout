# Scout — полный гайд с нуля

Один документ: от `git clone` до автопилота на сервере.

**Что делает Scout:** Яндекс.Карты → аудит сайта → персональное письмо → отправка → follow-up → дашборд.

---

## Содержание

1. [Требования](#1-требования)
2. [Установка](#2-установка)
3. [Настройка `.env`](#3-настройка-env)
4. [Почта (чтобы не было спама)](#4-почта-чтобы-не-было-спама)
5. [Локальный запуск](#5-локальный-запуск)
6. [Деплой на сервер (PM2)](#6-деплой-на-сервер-pm2)
7. [Автопилот (cron)](#7-автопилот-cron)
8. [Telegram и IMAP](#8-telegram-и-imap)
9. [Первый запуск и проверка](#9-первый-запуск-и-проверка)
10. [Ежедневная рутина](#10-ежедневная-рутина)
11. [Команды](#11-команды)
12. [Типичные проблемы](#12-типичные-проблемы)

---

## 1. Требования

| Компонент | Зачем |
|-----------|--------|
| Python 3.11+ | Scout |
| Node.js 18+ | IndexLift SEO (опционально) |
| PM2 | Веб-UI на сервере 24/7 |
| Chromium (Playwright) | Сбор с Яндекс.Карт |
| GPTunnel API key | LLM для писем |
| SMTP | Отправка email |
| Домен с SPF + DKIM | Доставляемость |

**На Linux-сервере дополнительно:**

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

---

## 2. Установка

```bash
git clone <ваш-репо> /opt/scout-app
cd /opt/scout-app

make install
```

Playwright на Linux (обязательно на сервере):

```bash
cd scout
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium
```

IndexLift (опционально, для SEO-аудита слабых сайтов):

```bash
# skill должен быть на сервере
npm install --prefix ~/.agents/skills/indexlift-seo-auditor
```

Создайте конфиг:

```bash
cp scout/.env.example scout/.env
nano scout/.env
```

---

## 3. Настройка `.env`

Файл: `scout/.env`. Шаблон: `scout/.env.example`.

### Обязательно

```env
# LLM
GPTUNNEL_API_KEY=ваш-ключ

# Почта — From и User должны быть одного домена
SMTP_HOST=mail.webstroke.ru
SMTP_PORT=587
SMTP_USER=admin@webstroke.ru
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=admin@webstroke.ru
SMTP_FROM_NAME=ВебШтрих
SMTP_USE_TLS=true

# Автопилот
AUTO_SEND_EMAIL=true
AUTOPILOT_ENABLED=true
```

### Экономия LLM (рекомендуется)

```env
AGENT_LITE_MODE=true
LLM_DAILY_BUDGET_RUB=50
FIT_SCORE_THRESHOLD=65
AUTO_SEND_MIN_FIT_SCORE=70
FOLLOWUP_COUNT=1
FOLLOWUP_MIN_FIT_SCORE=75
INDEXLIFT_ONLY_BELOW_SCORE=70
```

### Антиспам

```env
MAX_EMAILS_PER_DAY=20
MAX_EMAILS_PER_HOUR=6
MAX_EMAILS_PER_DOMAIN_PER_DAY=1
SEND_DELAY_SEC_MIN=60
SEND_DELAY_SEC_MAX=180
```

Первые 2 недели поставьте `MAX_EMAILS_PER_DAY=10` для прогрева ящика.

### Сервер (PM2)

```env
SCOUT_BIND_HOST=0.0.0.0
SCOUT_BIND_PORT=8080
SCOUT_AUTH_USER=admin
SCOUT_AUTH_PASSWORD=длинный-случайный-пароль
SCOUT_SECRET_KEY=...          # openssl rand -hex 32
SCOUT_REQUIRE_AUTH=true
# SCOUT_ALLOWED_IPS=ваш.ip.адрес
```

### Telegram (дайджест + READY-лиды)

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Как получить: [@BotFather](https://t.me/BotFather) → `/newbot` → токен.  
Chat ID: напишите боту, откройте `https://api.telegram.org/bot<TOKEN>/getUpdates`.

### IMAP (уведомления об ответах)

```env
IMAP_CHECK_ENABLED=true
IMAP_HOST=mail.webstroke.ru
IMAP_PORT=993
IMAP_USER=admin@webstroke.ru
IMAP_PASSWORD=...
IMAP_USE_SSL=true
```

---

## 4. Почта (чтобы не было спама)

Scout не решает доставляемость — это настройка домена.

### Чеклист

| Проверка | Как |
|----------|-----|
| SPF | DNS `webstroke.ru` → TXT `v=spf1 ...` |
| DKIM | Включить в панели почты, ключ в DNS |
| DMARC | TXT `_dmarc.webstroke.ru` |
| **PTR (rDNS)** | Тикет хостеру: IP → `mail.webstroke.ru` |
| SSL на mail | Let's Encrypt на `mail.webstroke.ru` |
| Тест | [mail-tester.com](https://www.mail-tester.com) → цель 8+/10 |

### Что должно быть в mail-tester

```
spf=pass
dkim=pass
dmarc=pass
```

Если `RDNS_NONE` — закажите PTR у хостера VPS. Это главная причина спама при своём mail-сервере.

### Альтернатива своему mail-серверу

Яндекс 360 на домене `webstroke.ru` — SPF/DKIM из коробки:

```env
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=587
SMTP_TLS_REJECT_UNAUTHORIZED=1
```

---

## 5. Локальный запуск

```bash
cd /opt/scout-app   # или путь к проекту
make run
```

- UI: http://localhost:8080  
- Дашборд: http://localhost:8080/dashboard  

Тестовая кампания вручную:

```bash
make blast PRESET=production CITY="Ростов-на-Дону" LIMIT=5 SEND=1
```

---

## 6. Деплой на сервер (PM2)

PM2 держит **только веб-интерфейс**. Кампании запускает cron (следующий раздел).

```bash
cd /opt/scout-app
mkdir -p scout/logs scout/data

pm2 start ecosystem.config.cjs
pm2 status
pm2 logs scout
pm2 save
pm2 startup    # автозапуск после перезагрузки сервера
```

Откройте: `http://IP_СЕРВЕРА:8080` → логин.

### Файрвол

```bash
sudo ufw allow from ВАШ_IP to any port 8080 proto tcp
sudo ufw enable
```

Безопаснее: SSH-туннель вместо открытого порта:

```bash
# На сервере: SCOUT_BIND_HOST=127.0.0.1
# Локально:
ssh -L 8080:127.0.0.1:8080 user@server
```

### Обновление

```bash
cd /opt/scout-app
git pull
make install
pm2 restart scout
```

---

## 7. Автопилот (cron)

**Без cron автопилот не работает.** PM2 ≠ автопилот.

### Что делает cron каждый будний день

```
10:00 → IMAP (ответы) → follow-up (D+3, D+7) → кампания из очереди → Telegram-отчёт
```

Очередь кампаний: `scout/autopilot/queue.yaml` (производство, опт, логистика × Ростов/Краснодар).

### Настройка

```bash
chmod +x scout/scripts/cron_daily.sh
crontab -e
```

Добавьте строку (путь замените на свой):

```cron
0 10 * * 1-5 cd /opt/scout-app && scout/scripts/cron_daily.sh >> scout/logs/cron.log 2>&1
```

Проверка логов:

```bash
tail -f scout/logs/cron.log
```

### Ручной запуск (тест)

```bash
make autopilot-daily FORCE=1
```

---

## 8. Telegram и IMAP

| Канал | Что приходит |
|-------|--------------|
| Telegram | Отчёт кампании, LLM-бюджет, ссылки WhatsApp/TG для ручной отправки |
| IMAP | «Ответ от лида» когда кто-то ответил на ваше письмо |

Без Telegram вы смотрите дашборд вручную.  
Без IMAP — ответы только в почтовом ящике.

---

## 9. Первый запуск и проверка

### Чеклист перед «пусть живёт»

```
□ make install — без ошибок
□ scout/.env — все обязательные поля заполнены
□ mail-tester.com — 8+/10, PTR настроен
□ make autopilot-daily FORCE=1 — кампания прошла
□ Дашборд — лиды, статусы sent/ready
□ Telegram — пришёл отчёт (если настроен)
□ crontab — строка с cron_daily.sh
□ pm2 status — scout online
□ MAX_EMAILS_PER_DAY=10 на первые 2 недели
```

### Что увидите в дашборде

| Статус | Значение |
|--------|----------|
| `sent` | Email отправлен автоматически |
| `ready` | Нет email — ссылка на WhatsApp/TG (клик вручную или из Telegram) |
| `duplicate` | Уже писали этому контакту |
| `pending` | Fit < 70 — письмо есть, автоотправка пропущена |

---

## 10. Ежедневная рутина

**~10 минут в день** (остальное автоматически):

1. Прочитать Telegram-дайджест (или дашборд)
2. Ответить на входящие / договориться о созвоне
3. Кликнуть ссылки READY-лидов для WhatsApp/TG
4. Раз в неделю — глянуть `scout/logs/cron.log` на ошибки

---

## 11. Команды

Все из корня проекта:

| Команда | Что делает |
|---------|------------|
| `make install` | Установка зависимостей |
| `make run` | UI локально (dev) |
| `make pm2` | Запуск через PM2 |
| `make autopilot-daily` | Полный цикл: IMAP + follow-up + кампания |
| `make autopilot` | Одна кампания из очереди |
| `make followups-due` | Только просроченные follow-up |
| `make inbox` | Проверить ответы на почте |
| `make blast PRESET=production SEND=1` | Ручная кампания |
| `make presets` | Список пресетов |
| `make dashboard` | URL дашборда |

---

## 12. Типичные проблемы

### «Кампания не запускается сама»

PM2 только UI. Проверьте `crontab -l` и `scout/logs/cron.log`.

### «AUTOPILOT_ENABLED=false»

В `.env`: `AUTOPILOT_ENABLED=true` или `make autopilot-daily FORCE=1`.

### «LLM budget exceeded»

Дневной лимит `LLM_DAILY_BUDGET_RUB` исчерпан. Увеличьте или ждите следующий день.

### «Не удалось собрать организации»

Все компании из запроса уже в базе. Смените query/город в `scout/autopilot/queue.yaml`.

### Письма в спаме

1. mail-tester.com → исправить PTR  
2. Снизить `MAX_EMAILS_PER_DAY` до 10  
3. Проверить `SMTP_FROM_EMAIL` = `SMTP_USER`

### Playwright на Linux падает

```bash
scout/.venv/bin/playwright install-deps chromium
```

### IndexLift не работает

Не критично — Scout использует Python-аудит. Отключите: `INDEXLIFT_ENABLED=false`.

---

## Архитектура (кратко)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ cron 10:00  │────▶│ Scout CLI    │────▶│ Яндекс.Карты│
│ (будни)     │     │ autopilot    │     │ Playwright  │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────▼───────┐
                    │ LLM (lite)   │  ~5-10 ₽/день
                    │ + prefilter  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           SMTP         Telegram      SQLite
         (email)       (дайджест)   (дашборд)
              │
         PM2 :8080 (UI)
```

---

## Связанные файлы

| Файл | Назначение |
|------|------------|
| `scout/.env.example` | Все переменные |
| `scout/autopilot/queue.yaml` | Очередь кампаний |
| `scout/presets/*.yaml` | Ниши (производство, опт, логистика) |
| `.agents/product-marketing.md` | Контекст ВебШтрих для писем |
| `ecosystem.config.cjs` | PM2 |
| `scout/scripts/cron_daily.sh` | Скрипт для cron |
