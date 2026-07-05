#!/usr/bin/env bash
# Обновление на сервере: git pull → deps → UI → PM2 → health.
# Вызывается из GitHub Actions (deploy.yml) или вручную после первого ./deploy.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\033[1;34m→\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

log "MyAI server update ($ROOT)"

if [[ ! -f scout/.env ]]; then
  die "scout/.env не найден. Сначала один раз: ./deploy.sh"
fi

if [[ ! -d scout/.venv ]]; then
  die "scout/.venv не найден. Сначала: ./deploy.sh"
fi

BRANCH="${DEPLOY_BRANCH:-main}"
log "git pull origin $BRANCH"
git fetch origin "$BRANCH"
git checkout "$BRANCH" 2>/dev/null || true
git pull --ff-only origin "$BRANCH"
ok "код обновлён ($(git rev-parse --short HEAD))"

log "Python-зависимости"
scout/.venv/bin/pip install -q --upgrade pip
scout/.venv/bin/pip install -q -r scout/requirements.txt
scout/.venv/bin/pip install -q -r office/requirements.txt
ok "pip"

mkdir -p scout/logs scout/data office/logs office/data
mkdir -p scout/data/cursor/{pending,reports,done,verdicts}
chmod +x scout/scripts/*.sh scripts/*.sh 2>/dev/null || true

if command -v npm >/dev/null 2>&1; then
  log "Office UI"
  (
    cd office/ui
    if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
    npm run build
  )
  ok "office/ui/dist"
else
  echo "! npm не найден — Office UI не пересобран" >&2
fi

log "Проверка импорта"
PYTHONPATH="$ROOT" scout/.venv/bin/python -c "
from scout.app.main import app
from office.api.main import app as office_app
print('scout:', len(app.routes), 'office:', len(office_app.routes))
"
ok "приложения загружаются"

if command -v pm2 >/dev/null 2>&1; then
  log "PM2 reload"
  if pm2 describe scout >/dev/null 2>&1; then
    pm2 reload ecosystem.config.cjs --update-env
  else
    pm2 start ecosystem.config.cjs
  fi
  pm2 save 2>/dev/null || true
  ok "PM2"
else
  die "PM2 не установлен. Запустите ./deploy.sh на сервере"
fi

log "Health checks"
sleep 2
SCOUT_PORT="$(python3 - <<'PY'
import re
from pathlib import Path
p = Path("scout/.env")
port = "8080"
if p.is_file():
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^SCOUT_BIND_PORT\s*=\s*(\d+)", line.strip(), re.I)
        if m:
            port = m.group(1)
            break
print(port)
PY
)"
OFFICE_PORT="$(python3 - <<'PY'
import re
from pathlib import Path
p = Path("scout/.env")
port = "8090"
if p.is_file():
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^OFFICE_BIND_PORT\s*=\s*(\d+)", line.strip(), re.I)
        if m:
            port = m.group(1)
            break
print(port)
PY
)"

curl -sf "http://127.0.0.1:${SCOUT_PORT}/health" | grep -q '"status"' \
  || die "Scout health failed (:${SCOUT_PORT})"
curl -sf "http://127.0.0.1:${OFFICE_PORT}/health" | grep -q '"status"' \
  || die "Office health failed (:${OFFICE_PORT})"
ok "health OK (scout:${SCOUT_PORT}, office:${OFFICE_PORT})"

if [[ "${CURSOR_GIT_SYNC_ENABLED:-false}" == "true" ]]; then
  log "Cursor git sync"
  ./scripts/cursor_git_sync.sh || echo "! cursor_git_sync failed (see scout/logs/cursor-sync.log)" >&2
fi

ok "деплой завершён"
