# MyAI — AI Scout + Маркетинговый отдел

B2B-аутрич и AI-маркетинг: Яндекс.Карты → письма → CRM → контент → реклама.

## Одна команда на сервер

```bash
git clone <ваш-репо> /opt/myai
cd /opt/myai
./deploy.sh
```

Скрипт сам: venv, зависимости, Chromium, `scout/.env` с паролем, PM2 (UI + планировщик), каталоги данных.

После установки — допишите в `scout/.env`: `GPTUNNEL_API_KEY`, `SMTP_*`.

```bash
nano scout/.env
pm2 restart all
```

**Локально (Mac):**

```bash
make install          # или ./deploy.sh --local --skip-pm2
make local-dev        # UI + планировщик
```

## Быстрый старт (вручную)

**Полный гайд:** [scout/SETUP.md](scout/SETUP.md)

```bash
make install
make run                           # http://localhost:8080
```

## Автопилот на сервере

```bash
pm2 start ecosystem.config.cjs     # UI 24/7
# + cron (см. scout/SETUP.md §7)
make autopilot-daily FORCE=1       # тестовый прогон
```

## Документация

| Файл | Содержание |
|------|------------|
| [scout/SETUP.md](scout/SETUP.md) | **Главный гайд** — всё с нуля |
| [scout/README.md](scout/README.md) | Pipeline, пресеты, продажа Scout |
| [scout/DEPLOY.md](scout/DEPLOY.md) | Кратко про PM2 и файрвол |
| [.cursor/automations/README.md](.cursor/automations/README.md) | Cursor Automations для Department |

## AI Marketing Department

Полный маркетинговый отдел из 6 агентов (CMO, Sales, SMM, Ads, SEO, Analytics):

```bash
make department-daily FORCE=1   # полный цикл: autopilot → analytics → CMO → агенты
```

UI: http://localhost:8080/department

Cron (`scout/scripts/cron_daily.sh`) вызывает `department daily`.

## Что работает из коробки

| Возможность | Статус |
|-------------|--------|
| Сбор с Яндекс.Карт (Playwright) | ✅ по умолчанию |
| Сбор через **2GIS API** | ✅ при `TWOGIS_API_KEY` + `MAPS_COLLECTOR=2gis` |
| AI-письма (GPTunnel) | ✅ при ключе; лимит `LLM_DAILY_BUDGET_RUB` |
| Фильтр выручки **500k ₽/мес** (DaData) | ✅ при `DADATA_API_KEY` + `REVENUE_FILTER_ENABLED=true` |
| Отправка email | ✅ при настроенном SMTP |
| ICP «доставка еды» | ✅ пресет `food-delivery` по умолчанию |
| Маркетинговый отдел (6 агентов) | ✅ `/department` |
| Cursor Automations | ⚙️ webhook + sync через GitHub (см. `.cursor/automations/README.md`) |
