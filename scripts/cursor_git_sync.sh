#!/usr/bin/env bash
# Синхронизация handoffs/verdicts с GitHub для Cursor Cloud Agents.
# Включить: CURSOR_GIT_SYNC_ENABLED=true в scout/.env
# Cron: */5 * * * * cd /opt/myai && scripts/cursor_git_sync.sh >> scout/logs/cursor-sync.log 2>&1
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${CURSOR_GIT_SYNC_ENABLED:-false}" != "true" ]]; then
  exit 0
fi

if [[ ! -f scout/.env ]]; then
  echo "scout/.env не найден" >&2
  exit 1
fi

export PYTHONPATH="$ROOT"
GIT_BRANCH="${CURSOR_GIT_BRANCH:-main}"

git config user.email "${CURSOR_GIT_EMAIL:-myai@localhost}"
git config user.name "${CURSOR_GIT_NAME:-MyAI Server}"

shopt -s nullglob

# Push новые handoffs (force-add — json в .gitignore)
pending=(scout/data/cursor/pending/*.json)
if ((${#pending[@]})); then
  git add -f scout/data/cursor/pending/*.json
  if ! git diff --cached --quiet; then
    git commit -m "chore(cursor): server handoffs [skip ci]"
    git push origin "HEAD:${GIT_BRANCH}"
    echo "$(date -Iseconds) pushed ${#pending[@]} pending file(s)"
  fi
fi

# Pull verdicts от Cursor Agent
git pull --ff-only origin "$GIT_BRANCH" 2>/dev/null || git pull --rebase origin "$GIT_BRANCH" || true

# Применить verdicts локально
if [[ -x scout/.venv/bin/python ]]; then
  scout/.venv/bin/python scout/scripts/office_cli.py ingest 2>/dev/null || true
  scout/.venv/bin/python - <<'PY'
import asyncio
from scout.department.integrations.cursor_bridge import apply_verdicts_from_files

n = asyncio.run(apply_verdicts_from_files())
print(f"department verdicts applied: {n}")
PY
fi

# Закоммитить обработанные verdicts (done/) если нужно — опционально, не пушим done

echo "$(date -Iseconds) cursor git sync OK"
