#!/usr/bin/env bash
# MyAI Scout + Marketing Department — установка и запуск одной командой.
#
#   git clone <repo> /opt/myai && cd /opt/myai && ./deploy.sh
#
# Флаги:
#   --local          ноутбук: 127.0.0.1, без обязательной авторизации
#   --skip-pm2       только установка, без PM2
#   --skip-browser   без Playwright (если не нужны Яндекс.Карты)
#   --with-cron      добавить cron (будни 10:00) — доп. к планировщику PM2
#   --with-cursor-sync  cron каждые 5 мин: push handoffs / pull verdicts (Cursor Cloud)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOCAL=0
SKIP_PM2=0
SKIP_BROWSER=0
WITH_CRON=0
WITH_CURSOR_SYNC=0

for arg in "$@"; do
  case "$arg" in
    --local) LOCAL=1 ;;
    --skip-pm2) SKIP_PM2=1 ;;
    --skip-browser) SKIP_BROWSER=1 ;;
    --with-cron) WITH_CRON=1 ;;
    --with-cursor-sync) WITH_CURSOR_SYNC=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Неизвестный аргумент: $arg (см. ./deploy.sh --help)" >&2
      exit 1
      ;;
  esac
done

log() { printf '\033[1;34m→\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
ARCH="$(uname -m)"

log "MyAI — установка ($OS $ARCH)"

# --- Python ---
if ! command -v python3 >/dev/null 2>&1; then
  die "Нужен Python 3.11+. Ubuntu: sudo apt install -y python3 python3-venv python3-pip"
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VER%%.*}"
PY_MINOR="${PY_VER#*.}"
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
  die "Нужен Python 3.11+, найден $PY_VER"
fi
ok "Python $PY_VER"

# --- Системные пакеты (Linux) ---
if [[ "$OS" == "Linux" ]] && command -v apt-get >/dev/null 2>&1; then
  MISSING=()
  for pkg in python3-venv python3-pip curl; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING+=("$pkg")
  done
  if ((${#MISSING[@]})); then
    if command -v sudo >/dev/null 2>&1; then
      log "Ставим системные пакеты: ${MISSING[*]}"
      sudo apt-get update -qq
      sudo apt-get install -y "${MISSING[@]}"
    else
      warn "Не хватает пакетов: ${MISSING[*]}. Установите вручную (sudo apt install ...)"
    fi
  fi
fi

# --- Каталоги ---
log "Каталоги данных"
mkdir -p scout/logs scout/data office/logs office/data
mkdir -p scout/data/cursor/{pending,reports,done,verdicts}
chmod +x scout/scripts/*.sh office/scripts/*.sh scripts/*.sh 2>/dev/null || true
ok "scout/logs, scout/data, office/, cursor handoffs"

# --- .env ---
log "Конфиг scout/.env"
BOOT_ARGS=()
[[ "$LOCAL" -eq 1 ]] && BOOT_ARGS+=(--local)
python3 scout/scripts/bootstrap_env.py "${BOOT_ARGS[@]}"
ok "scout/.env готов"

# --- venv + pip ---
log "Python-зависимости"
if [[ ! -d scout/.venv ]]; then
  python3 -m venv scout/.venv
fi
scout/.venv/bin/pip install -q --upgrade pip
scout/.venv/bin/pip install -q -r scout/requirements.txt
scout/.venv/bin/pip install -q -r office/requirements.txt
ok "venv + scout + office requirements"

# --- Playwright ---
if [[ "$SKIP_BROWSER" -eq 0 ]]; then
  log "Chromium для Playwright"
  scout/.venv/bin/playwright install chromium
  if [[ "$OS" == "Linux" ]]; then
    if scout/.venv/bin/playwright install-deps chromium 2>/dev/null; then
      ok "Playwright + системные libs"
    elif command -v sudo >/dev/null 2>&1; then
      warn "Нужны системные библиотеки для Chromium — запускаю install-deps с sudo"
      sudo scout/.venv/bin/playwright install-deps chromium || warn "install-deps не удался — см. scout/SETUP.md"
    else
      warn "Запустите: scout/.venv/bin/playwright install-deps chromium"
    fi
  else
    ok "Playwright Chromium"
  fi
else
  warn "Playwright пропущен (--skip-browser)"
fi

# --- Проверка старта ---
log "Проверка импорта"
PYTHONPATH="$ROOT" scout/.venv/bin/python -c "from scout.app.main import app; from office.api.main import app as oa; print('scout:', len(app.routes), 'office:', len(oa.routes))"
ok "Приложение загружается"

# --- Office UI ---
if command -v npm >/dev/null 2>&1; then
  log "Office UI (npm build)"
  (
    cd office/ui
    if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
    npm run build
  )
  ok "Office UI → office/ui/dist"
else
  warn "npm не найден — Office UI не собран. Ubuntu: Node 20+ → make office-ui"
fi

# --- PM2 ---
if [[ "$SKIP_PM2" -eq 0 ]]; then
  if ! command -v pm2 >/dev/null 2>&1; then
    if command -v npm >/dev/null 2>&1; then
      log "Устанавливаем PM2 (npm -g pm2)"
      npm install -g pm2
    else
      warn "PM2 не найден. Ubuntu: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs && sudo npm i -g pm2"
      warn "Или запустите вручную: make run"
      SKIP_PM2=1
    fi
  fi

  if [[ "$SKIP_PM2" -eq 0 ]]; then
    log "PM2: веб-UI + планировщик маркетинга"
    pm2 delete scout department-scheduler office 2>/dev/null || true
    pm2 start ecosystem.config.cjs
    pm2 save 2>/dev/null || true
    ok "PM2 процессы запущены"
    if [[ "$OS" == "Linux" ]] && command -v sudo >/dev/null 2>&1; then
      warn "После перезагрузки сервера выполните один раз:"
      echo "       sudo env PATH=\$PATH pm2 startup systemd -u \$USER --hp \$HOME"
      echo "       pm2 save"
    fi
  fi
fi

# --- Cursor git sync (опционально) ---
if [[ "$WITH_CURSOR_SYNC" -eq 1 ]]; then
  if grep -q '^CURSOR_GIT_SYNC_ENABLED=' scout/.env 2>/dev/null; then
    sed -i.bak 's/^CURSOR_GIT_SYNC_ENABLED=.*/CURSOR_GIT_SYNC_ENABLED=true/' scout/.env
    rm -f scout/.env.bak
  else
    echo "CURSOR_GIT_SYNC_ENABLED=true" >> scout/.env
  fi
  SYNC_LINE="*/5 * * * * cd $ROOT && scripts/cursor_git_sync.sh >> scout/logs/cursor-sync.log 2>&1"
  if crontab -l 2>/dev/null | grep -Fq "cursor_git_sync.sh"; then
    ok "Cursor git sync cron уже настроен"
  else
    (crontab -l 2>/dev/null; echo "$SYNC_LINE") | crontab -
    ok "Cron: каждые 5 мин → cursor handoffs ↔ GitHub"
  fi
  warn "Настройте git push с сервера (deploy key): docs/CICD.md"
fi

# --- Cron (опционально) ---
if [[ "$WITH_CRON" -eq 1 ]]; then
  CRON_LINE="0 10 * * 1-5 cd $ROOT && scout/scripts/cron_daily.sh >> scout/logs/cron.log 2>&1"
  if crontab -l 2>/dev/null | grep -Fq "scout/scripts/cron_daily.sh"; then
    ok "Cron уже настроен"
  else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    ok "Cron: будни 10:00 → department daily"
  fi
fi

# --- Итог ---
read_env() {
  python3 - "$1" "${2:-}" <<'PY'
import re, sys
from pathlib import Path
key, default = sys.argv[1], sys.argv[2]
path = Path("scout/.env")
if not path.is_file():
    print(default)
    raise SystemExit
for line in reversed(path.read_text(encoding="utf-8").splitlines()):
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    m = re.match(rf"^{re.escape(key)}\s*=\s*(.*)$", s, re.I)
    if m:
        val = m.group(1).strip()
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        print(val or default)
        raise SystemExit
print(default)
PY
}

HOST="$(read_env SCOUT_BIND_HOST 127.0.0.1)"
PORT="$(read_env SCOUT_BIND_PORT 8080)"
USER_NAME="$(read_env SCOUT_AUTH_USER admin)"
PASS="$(read_env SCOUT_AUTH_PASSWORD '')"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  MyAI Scout + Маркетинговый отдел — готово"
echo "════════════════════════════════════════════════════════"
echo ""
if [[ "$HOST" == "0.0.0.0" ]]; then
  SERVER_IP="$(curl -s --max-time 2 ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo 'IP_СЕРВЕРА')"
  echo "  UI:        http://${SERVER_IP}:${PORT}"
else
  echo "  UI:        http://${HOST}:${PORT}"
fi
echo "  Маркетинг: http://${HOST}:${PORT}/department"
OFFICE_PORT="$(read_env OFFICE_BIND_PORT 8090)"
OFFICE_HOST="$(read_env OFFICE_BIND_HOST 127.0.0.1)"
echo "  AI Office: http://${OFFICE_HOST}:${OFFICE_PORT}/office"
if [[ -n "$PASS" ]]; then
  echo "  Логин:     ${USER_NAME}"
  echo "  Пароль:    ${PASS}"
fi
echo ""
echo "  Дальше отредактируйте scout/.env:"
echo "    GPTUNNEL_API_KEY  — для писем и аутрича"
echo "    SMTP_*            — отправка email"
echo "    TELEGRAM_*        — уведомления (опционально)"
echo ""
if [[ "$SKIP_PM2" -eq 0 ]] && command -v pm2 >/dev/null 2>&1; then
  echo "  PM2:       pm2 status | pm2 logs"
  echo "  Стоп:      pm2 stop all"
  echo "  Рестарт:   pm2 restart all"
else
  echo "  Запуск:    make run"
  echo "  Планировщик: make department-scheduler"
fi
echo ""
echo "  Полный гайд: scout/SETUP.md"
echo "════════════════════════════════════════════════════════"
