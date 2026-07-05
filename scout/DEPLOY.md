# Деплой Scout на сервер (PM2, без домена)

> **Полный гайд с нуля:** [SETUP.md](SETUP.md) — установка, `.env`, почта, cron, автопилот.

## Одна команда

```bash
git clone <ваш-репо> /opt/myai
cd /opt/myai
./deploy.sh
```

Скрипт установит Python-зависимости, Chromium, создаст `scout/.env` с паролем, запустит PM2 (веб + планировщик маркетинга). Допишите `GPTUNNEL_API_KEY` и `SMTP_*`, затем `pm2 restart all`.

Доступ по IP: `http://ВАШ_IP:8080`. Обязательны логин/пароль. Опционально — белый список IP.

## 1. Сервер (если без deploy.sh)

Нужно: **Python 3.11+**, **Node.js** (для IndexLift SEO, опционально), **PM2**.

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-venv git
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

## 2. Код на сервер

```bash
git clone <ваш-репо> /opt/scout-app
cd /opt/scout-app
make install
```

Playwright (для Яндекс.Карт):

```bash
cd /opt/scout-app/scout
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium   # системные библиотеки на Linux
```

IndexLift (если включён в `.env`):

```bash
# скопируйте skill на сервер или укажите INDEXLIFT_SKILL_PATH
npm install --prefix ~/.agents/skills/indexlift-seo-auditor
```

## 3. Конфиг `scout/.env`

```bash
cp scout/.env.example scout/.env
nano scout/.env
```

**Обязательно для сервера:**

```env
# Доступ по IP — слушаем все интерфейсы
SCOUT_BIND_HOST=0.0.0.0
SCOUT_BIND_PORT=8080

# Авторизация (без пароля сервер не стартует)
SCOUT_AUTH_USER=admin
SCOUT_AUTH_PASSWORD=длинный-случайный-пароль
SCOUT_SECRET_KEY=сгенерируйте: openssl rand -hex 32
SCOUT_REQUIRE_AUTH=true

# Только ваши IP (рекомендуется). Через запятую, CIDR ок:
# SCOUT_ALLOWED_IPS=1.2.3.4,5.6.7.8/32

GPTUNNEL_API_KEY=...
# SMTP и остальное — как локально
```

Пароль и secret key **не коммитьте** в git.

## 4. PM2

```bash
cd /opt/scout-app
mkdir -p scout/logs scout/data
pm2 start ecosystem.config.cjs
pm2 status
pm2 logs scout
pm2 save
pm2 startup   # автозапуск после перезагрузки
```

Открыть в браузере: `http://IP_СЕРВЕРА:8080` → форма входа.

## 5. Файрвол

Откройте порт **только** для своих IP:

```bash
# ufw пример
sudo ufw allow from ВАШ_IP to any port 8080 proto tcp
sudo ufw enable
```

Без HTTPS пароль идёт по сети открытым текстом после логина (cookie). Для максимальной безопасности без домена:

- **Вариант A:** `SCOUT_BIND_HOST=127.0.0.1` + SSH-туннель:  
  `ssh -L 8080:127.0.0.1:8080 user@server`
- **Вариант B:** `SCOUT_ALLOWED_IPS` + файрвол только на ваш IP

## 6. Обновление

```bash
cd /opt/scout-app
git pull
make install   # если менялись зависимости
make office-ui # если менялся Office UI
pm2 restart all
```

**Автоматически:** push в `main` → GitHub Actions деплой. См. [docs/CICD.md](../docs/CICD.md).

## 7. CLI на сервере

```bash
cd /opt/scout-app
export PYTHONPATH=.
set -a && source scout/.env && set +a
scout/.venv/bin/python -m scout.cli blast --preset production --limit 5
```

## 8. Автопилот (cron)

PM2 **не** запускает кампании. Нужен cron — см. [SETUP.md §7](SETUP.md#7-автопилот-cron).

```bash
chmod +x scout/scripts/cron_daily.sh
crontab -e
# 0 10 * * 1-5 cd /opt/scout-app && scout/scripts/cron_daily.sh >> scout/logs/cron.log 2>&1
```
