#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f scout/.env ]]; then
  echo "Ошибка: scout/.env не найден" >&2
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

HOST="${OFFICE_BIND_HOST:-127.0.0.1}"
PORT="${OFFICE_BIND_PORT:-8090}"

exec scout/.venv/bin/uvicorn office.api.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*"
