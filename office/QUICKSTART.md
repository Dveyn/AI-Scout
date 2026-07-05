# Как пользоваться AI Office (локально)

## Суть

**Вы даёте одну задачу → получаете готовый результат.**  
Координацию делает COO, работу — отделы. У вас `DEPARTMENT_LLM_PROVIDER=cursor` — тяжёлая работа идёт через **Cursor Automation** (подписка), не GPTunnel.

---

## Шаг 1 — один раз настроить Cursor Automation

1. Откройте **Cursor → Agents → Automations → /automate**
2. Импортируйте файл: `.cursor/automations/office-directive.yaml`
3. Сохраните automation и скопируйте webhook URL в `scout/.env`:
   ```env
   CURSOR_WEBHOOK_OFFICE_DIRECTIVE=https://api2.cursor.sh/automations/webhook/...
   ```
   (Пока можно не создавать отдельный — используется `CURSOR_WEBHOOK_DEPARTMENT_DAILY`)

4. **GitHub**: репозиторий должен быть подключён к Cursor (cloud agent читает файлы из репо).

---

## Шаг 2 — запустить office локально

```bash
cd /Users/dmitrijananev/Desktop/work/MyAI
make office-ui          # один раз собрать UI
make office-dev         # http://localhost:8090/office
```

---

## Шаг 3 — дать задачу (выберите способ)

### A) Терминал (проще всего)

```bash
make office-task BRIEF="За 2 недели найти 3 B2B-клиента на портал"
```

Команда:
1. Создаёт файл `scout/data/cursor/pending/office-directive-*.json`
2. Вызывает webhook Cursor
3. Ждёт результат (до 10 мин)

Забрать результат вручную:
```bash
make office-ingest
# или по ID:
make office-result ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### B) Браузер

1. http://localhost:8090/office → вкладка **«👔 Задача»**
2. Напишите задачу → **«Отдать начальнику»**
3. Если статус «в Cursor» — кнопка **«Проверить результат»** (или подождите авто-опрос)

---

## Как это работает внутри

```
Вы (задача)
    ↓
pending/office-directive-{id}.json   ← локально
    ↓ webhook
Cursor Automation (COO + отделы)
    ↓
verdicts/office-directive-{id}.json  ← готовый результат
    ↓ make office-ingest / UI
office.db → вкладка «Задача»
```

---

## Если результат не приходит

| Проблема | Решение |
|----------|---------|
| Webhook не настроен | Добавьте `CURSOR_WEBHOOK_OFFICE_DIRECTIVE` или используйте `DEPARTMENT_DAILY` |
| Cursor не видит файл | **Закоммитьте и запушьте** `scout/data/cursor/pending/` в GitHub |
| Долго ждёте | `make office-ingest` — проверить verdicts |
| Хотите без Cursor | `OFFICE_LLM_PROVIDER=local` в scout/.env (жрёт GPTunnel) |

---

## Другие сервисы (уже работают)

| URL | Что |
|-----|-----|
| http://localhost:8090/office | CEO-кабинет |
| http://localhost:8080/department | Маркетинговый отдел Scout |
| `make department-daily` | Ежедневный цикл маркетинга |
