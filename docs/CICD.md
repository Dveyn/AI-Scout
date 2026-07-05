# CI/CD — автономный деплой на сервер

Автоматический пайплайн: **тесты на PR** → **деплой на `main`** → **PM2 24/7** → **планировщик маркетинга**.

## Архитектура

```
GitHub (main)
    │
    ├─ push/PR ──► CI (python + office UI build)
    │
    └─ push main ──► Deploy (SSH) ──► scripts/server_update.sh
                                           │
                                           ├─ git pull
                                           ├─ pip install
                                           ├─ npm build office/ui
                                           ├─ pm2 reload
                                           └─ health :8080 / :8090

Сервер (PM2)
    ├─ scout              :8080  — аутрич + /department
    ├─ department-scheduler      — цикл маркетинга каждые N мин
    └─ office             :8090  — CEO кабинет

Опционально (cron)
    ├─ cron_daily.sh             — будни 10:00
    └─ cursor_git_sync.sh        — каждые 5 мин (Cursor Cloud)
```

## 1. Первичная установка на сервере (один раз)

```bash
# На Ubuntu/Debian VPS
sudo apt update && sudo apt install -y git python3 python3-venv curl
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2

git clone https://github.com/Dveyn/AI-Scout.git /opt/myai
cd /opt/myai

# Сервер: 0.0.0.0, пароль, Cursor sync
./deploy.sh --with-cron --with-cursor-sync

nano scout/.env   # GPTUNNEL, SMTP, webhooks, SCOUT_BIND_HOST=0.0.0.0
pm2 restart all
sudo env PATH=$PATH pm2 startup systemd -u $USER --hp $HOME
pm2 save
```

Файрвол — только ваш IP на порты 8080/8090 (см. [DEPLOY.md](scout/DEPLOY.md)).

## 2. GitHub Secrets (для автодеплоя)

Репозиторий → **Settings → Secrets and variables → Actions**:

| Secret | Пример | Описание |
|--------|--------|----------|
| `DEPLOY_HOST` | `123.45.67.89` | IP или домен сервера |
| `DEPLOY_USER` | `deploy` | SSH-пользователь |
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH...` | Приватный ключ (полностью) |
| `DEPLOY_PATH` | `/opt/myai` | Каталог приложения (опционально) |
| `DEPLOY_PORT` | `22` | SSH-порт (опционально) |

### SSH-ключ для GitHub Actions

На **локальной машине**:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/myai_deploy -N ""
```

На **сервере** (`~/.ssh/authorized_keys`):

```bash
cat myai_deploy.pub >> ~/.ssh/authorized_keys
```

В **GitHub Secrets** → `DEPLOY_SSH_KEY` = содержимое `myai_deploy` (приватный ключ).

## 3. Что происходит при push в main

1. **CI** (`.github/workflows/ci.yml`) — импорт Scout/Office, сбор UI
2. **Deploy** (`.github/workflows/deploy.yml`) — SSH → `./scripts/server_update.sh`
3. Health: `GET /health` на Scout и Office

Коммиты с `[skip ci]` в сообщении **не** запускают деплой (нужно для `cursor_git_sync`).

Ручной деплой: **Actions → Deploy → Run workflow**.

## 4. Автономная работа

| Процесс | Как запускается |
|---------|-----------------|
| Scout UI | PM2 `scout` |
| Маркетинг (department daily) | PM2 `department-scheduler` |
| CEO Office | PM2 `office` |
| Дневной cron | `./deploy.sh --with-cron` |
| Cursor handoffs ↔ GitHub | `./deploy.sh --with-cursor-sync` |

Интервал планировщика: `DEPARTMENT_LOCAL_INTERVAL_MIN` в `scout/.env` (по умолчанию 60 мин).

На продакшене отключите тестовый режим:

```env
DEPARTMENT_TEST_MODE=false
SCOUT_BIND_HOST=0.0.0.0
SCOUT_REQUIRE_AUTH=true
```

## 5. Cursor Cloud на сервере

Cursor Agents читают handoffs из **GitHub**, не с диска сервера.

1. Включите sync: `CURSOR_GIT_SYNC_ENABLED=true` (или `./deploy.sh --with-cursor-sync`)
2. Настройте **deploy key с write** на сервере:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/myai_cursor_push -N ""
# GitHub → Repo → Settings → Deploy keys → Add (Allow write access)
cat ~/.ssh/myai_cursor_push.pub
```

```bash
cd /opt/myai
git remote -v   # origin = GitHub
# ~/.ssh/config:
# Host github.com
#   IdentityFile ~/.ssh/myai_cursor_push
```

3. Webhooks в `scout/.env` — см. [.cursor/automations/README.md](../.cursor/automations/README.md)

## 6. Обновление вручную (без CI)

```bash
cd /opt/myai
./scripts/server_update.sh
```

## 7. Nginx (опционально)

Пример reverse proxy: [deploy/nginx-myai.conf.example](deploy/nginx-myai.conf.example)

Scout и Office слушают `127.0.0.1` — снаружи только nginx с HTTPS.

## 8. Мониторинг

```bash
pm2 status
pm2 logs
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8090/health
tail -f scout/logs/department-scheduler.log
tail -f scout/logs/cursor-sync.log
```

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| Deploy failed: permission denied | Проверьте `DEPLOY_SSH_KEY`, `authorized_keys`, `DEPLOY_PATH` |
| Health failed после deploy | `pm2 logs office` — часто нет `office/ui/dist` → `make office-ui` |
| Cursor не видит задачи | `cursor_git_sync.sh`, deploy key write, `git push` вручную |
| Деплой зациклился | Убедитесь что sync-коммиты содержат `[skip ci]` |
| Office 8090 недоступен снаружи | `OFFICE_BIND_HOST=0.0.0.0` или nginx |
