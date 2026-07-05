#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f scout/.env ]]; then
  echo "Ошибка: создайте scout/.env (см. scout/.env.example)" >&2
  exit 1
fi

if [[ ! -x scout/.venv/bin/uvicorn ]]; then
  echo "Ошибка: scout/.venv не найден. Запустите: make install" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source scout/.env
set +a

export PYTHONPATH="$ROOT"

if [[ -z "${SCOUT_AUTH_PASSWORD:-}" ]]; then
  echo "Ошибка: задайте SCOUT_AUTH_PASSWORD в scout/.env" >&2
  exit 1
fi

if [[ -z "${SCOUT_SECRET_KEY:-}" ]]; then
  echo "Ошибка: задайте SCOUT_SECRET_KEY в scout/.env (openssl rand -hex 32)" >&2
  exit 1
fi

HOST="${SCOUT_BIND_HOST:-0.0.0.0}"
PORT="${SCOUT_BIND_PORT:-8080}"

exec scout/.venv/bin/uvicorn scout.app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*"
