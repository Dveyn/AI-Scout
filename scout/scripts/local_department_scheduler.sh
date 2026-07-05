#!/usr/bin/env bash
# Локальный планировщик AI Marketing Department (тестовый режим).
# Запуск: make department-scheduler
# Лог: scout/logs/department-scheduler.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f scout/.env ]]; then
  echo "Ошибка: scout/.env не найден" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source scout/.env
set +a

INTERVAL="${DEPARTMENT_LOCAL_INTERVAL_MIN:-60}"
export PYTHONPATH="$ROOT"

echo "$(date -Iseconds) local department scheduler started (interval ${INTERVAL}m)"

while true; do
  echo "$(date -Iseconds) --- cycle start ---"
  if scout/.venv/bin/python -m scout.cli department daily; then
    echo "$(date -Iseconds) cycle OK"
  else
    echo "$(date -Iseconds) cycle FAILED (see above)" >&2
  fi
  echo "$(date -Iseconds) next run in ${INTERVAL} minutes"
  sleep "$((INTERVAL * 60))"
done
