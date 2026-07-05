/**
 * PM2: Scout UI + планировщик маркетингового отдела
 *
 *   ./deploy.sh
 *   pm2 status
 *   pm2 logs
 */
module.exports = {
  apps: [
    {
      name: "scout",
      script: "scout/scripts/run_production.sh",
      interpreter: "bash",
      cwd: __dirname,
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      time: true,
      out_file: "scout/logs/pm2-scout-out.log",
      error_file: "scout/logs/pm2-scout-error.log",
      merge_logs: true,
    },
    {
      name: "department-scheduler",
      script: "scout/scripts/local_department_scheduler.sh",
      interpreter: "bash",
      cwd: __dirname,
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      min_uptime: "30s",
      time: true,
      out_file: "scout/logs/pm2-dept-out.log",
      error_file: "scout/logs/pm2-dept-error.log",
      merge_logs: true,
    },
    {
      name: "office",
      script: "scout/.venv/bin/uvicorn",
      args: "office.api.main:app --host 127.0.0.1 --port 8090",
      cwd: __dirname,
      env: { PYTHONPATH: __dirname },
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      time: true,
      out_file: "office/logs/pm2-office-out.log",
      error_file: "office/logs/pm2-office-error.log",
      merge_logs: true,
    },
  ],
};
