.PHONY: install deploy run cli blast send followup presets dashboard pm2 reset autopilot autopilot-daily followups-due inbox department-daily department-scheduler department-scheduler-stop local-dev office-install office-ui office-run office-dev office-task office-ingest office-result server-update cursor-sync

install:
	cd scout && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd scout && .venv/bin/pip install -r ../office/requirements.txt
	cd scout && .venv/bin/playwright install chromium
	python3 scout/scripts/bootstrap_env.py --local
	chmod +x scout/scripts/run_production.sh scout/scripts/local_department_scheduler.sh scout/scripts/cron_daily.sh office/scripts/run_production.sh deploy.sh scripts/server_update.sh scripts/cursor_git_sync.sh
	mkdir -p scout/logs scout/data scout/data/cursor/{pending,reports,done,verdicts}
	mkdir -p office/data office/ui/dist

deploy:
	chmod +x deploy.sh
	./deploy.sh

deploy-local:
	chmod +x deploy.sh
	./deploy.sh --local --skip-pm2

run:
	PYTHONPATH=. scout/.venv/bin/uvicorn scout.app.main:app --reload --port 8080

pm2:
	pm2 start ecosystem.config.cjs
	pm2 status

dashboard:
	@echo "http://localhost:8080/dashboard"

cli:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli run --query "$(QUERY)" --city "$(CITY)" --limit $(or $(LIMIT),5) --show-trace

blast:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli blast \
		--preset $(or $(PRESET),webstroke) \
		$(if $(QUERY),--query "$(QUERY)",) \
		$(if $(CITY),--city "$(CITY)",) \
		--limit $(or $(LIMIT),10) \
		$(if $(OFFER),--offer "$(OFFER)",) \
		$(if $(SEND),--send,)

send:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli send --job-id "$(JOB_ID)" --touch $(or $(TOUCH),1)

followup:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli send --job-id "$(JOB_ID)" --touch $(or $(TOUCH),2)

autopilot:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli autopilot run $(if $(FORCE),--force,)

autopilot-daily:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli autopilot daily $(if $(FORCE),--force,)

followups-due:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli autopilot followups

inbox:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli inbox

department-daily:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli department daily $(if $(FORCE),--force,)

department-scheduler:
	@chmod +x scout/scripts/local_department_scheduler.sh
	@mkdir -p scout/logs
	@if [ -f scout/logs/department-scheduler.pid ] && kill -0 $$(cat scout/logs/department-scheduler.pid) 2>/dev/null; then \
	  echo "Планировщик уже запущен (pid $$(cat scout/logs/department-scheduler.pid))"; \
	  echo "Лог: scout/logs/department-scheduler.log"; \
	else \
	  nohup scout/scripts/local_department_scheduler.sh >> scout/logs/department-scheduler.log 2>&1 & \
	  echo $$! > scout/logs/department-scheduler.pid; \
	  echo "Планировщик запущен pid $$!"; \
	  echo "Интервал: см. DEPARTMENT_LOCAL_INTERVAL_MIN в scout/.env"; \
	  echo "Лог: tail -f scout/logs/department-scheduler.log"; \
	fi

department-scheduler-stop:
	@if [ -f scout/logs/department-scheduler.pid ]; then \
	  kill $$(cat scout/logs/department-scheduler.pid) 2>/dev/null && echo "Остановлен" || echo "Процесс не найден"; \
	  rm -f scout/logs/department-scheduler.pid; \
	else \
	  echo "Планировщик не запущен"; \
	fi

local-dev: department-scheduler
	@echo "Планировщик в фоне. UI: http://localhost:8080/department"
	PYTHONPATH=. scout/.venv/bin/uvicorn scout.app.main:app --reload --port 8080

presets:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli presets

reset:
	PYTHONPATH=. scout/.venv/bin/python -m scout.cli reset --yes

office-install:
	cd scout && .venv/bin/pip install -r ../office/requirements.txt

office-ui:
	cd office/ui && npm install && npm run build

office-run:
	PYTHONPATH=. scout/.venv/bin/uvicorn office.api.main:app --reload --port 8090

office-dev:
	@echo "Office: http://localhost:8090/office → вкладка «Задача»"
	@echo "CLI:    make office-task BRIEF=\"ваша задача\""
	PYTHONPATH=. scout/.venv/bin/uvicorn office.api.main:app --reload --port 8090

office-task:
	@test -n "$(BRIEF)" || (echo 'Usage: make office-task BRIEF="найти 3 клиентов"' && exit 1)
	PYTHONPATH=. scout/.venv/bin/python scout/scripts/office_cli.py task "$(BRIEF)" --wait

office-ingest:
	PYTHONPATH=. scout/.venv/bin/python scout/scripts/office_cli.py ingest $(if $(ID),--id $(ID),)

office-result:
	@test -n "$(ID)" || (echo 'Usage: make office-result ID=<directive-id>' && exit 1)
	PYTHONPATH=. scout/.venv/bin/python scout/scripts/office_cli.py ingest --id $(ID)

server-update:
	chmod +x scripts/server_update.sh scripts/cursor_git_sync.sh
	./scripts/server_update.sh

cursor-sync:
	chmod +x scripts/cursor_git_sync.sh
	./scripts/cursor_git_sync.sh
