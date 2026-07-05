#!/usr/bin/env bash
# Ежедневный автопилот: follow-up → новая кампания из очереди.
#
# Crontab (каждый будний день в 10:00):
#   0 10 * * 1-5 cd /path/to/MyAI && scout/scripts/cron_daily.sh >> scout/logs/cron.log 2>&1
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f scout/.env ]]; then
  echo "Ошибка: scout/.env не найден" >&2
  exit 1
fi

export PYTHONPATH="$ROOT"
# Department daily cycle (autopilot + analytics + CMO + agents)
exec scout/.venv/bin/python -m scout.cli department daily
