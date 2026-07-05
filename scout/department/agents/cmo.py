from __future__ import annotations

import json
import logging

from scout.config import get_settings
from scout.department.base_agent import BaseAgent
from scout.department.models import (
    DailyReportRecord,
    DealRecord,
    DepartmentAgent,
    DepartmentTaskRecord,
    TaskStatus,
)
from scout.storage import department_db as db

logger = logging.getLogger(__name__)

AGENT_MAP = {
    "sales": DepartmentAgent.SALES,
    "smm": DepartmentAgent.SMM,
    "ads": DepartmentAgent.ADS,
    "seo": DepartmentAgent.SEO,
}


class CMOAgent(BaseAgent):
    agent_name = "cmo"

    async def review_and_plan(
        self,
        report: DailyReportRecord,
        deals: list[DealRecord],
    ) -> list[DepartmentTaskRecord]:
        settings = get_settings()
        deals_summary = [
            {"company": d.company_name, "status": d.status.value, "email": d.contact_email}
            for d in deals[:20]
        ]
        prompt = (
            f"Отчёт Analytics за {report.report_date}:\n"
            f"{report.summary}\n"
            f"KPI: {report.kpi.model_dump_json()}\n"
            f"Рекомендации: {json.dumps(report.recommendations, ensure_ascii=False)}\n\n"
            f"Воронка сделок ({len(deals)}):\n"
            f"{json.dumps(deals_summary, ensure_ascii=False)}\n\n"
            f"Сформируй стратегию на 7 дней и задачи для агентов."
        )
        result, summary, _ = await self.run(prompt, action="review_and_plan")
        tasks: list[DepartmentTaskRecord] = []

        for item in result.get("tasks", []):
            agent_key = str(item.get("agent", "smm")).lower()
            agent = AGENT_MAP.get(agent_key, DepartmentAgent.SMM)
            requires_approval = bool(item.get("requires_approval", False))
            if agent == DepartmentAgent.ADS and not settings.cmo_auto_approve_ads:
                requires_approval = True
            if agent == DepartmentAgent.SMM and not settings.cmo_auto_approve_smm:
                requires_approval = True
            if agent == DepartmentAgent.SEO and not settings.cmo_auto_approve_seo:
                requires_approval = True

            status = TaskStatus.PENDING
            if settings.cmo_mode == "review" or requires_approval:
                status = TaskStatus.PENDING_CMO_APPROVAL
            elif agent in (DepartmentAgent.SMM, DepartmentAgent.SEO):
                status = TaskStatus.APPROVED

            task = DepartmentTaskRecord(
                agent=agent,
                task_type=str(item.get("task_type", "content")),
                priority=int(item.get("priority", 5)),
                status=status,
                brief=str(item.get("brief", "")),
                input_json={"strategy_summary": result.get("strategy_summary", summary)},
                requires_approval=requires_approval,
            )
            tasks.append(await db.create_task(task))

        if not tasks:
            default_brief = result.get("strategy_summary", summary) or "Продолжить текущую стратегию"
            for agent, task_type in (
                (DepartmentAgent.SMM, "content_plan"),
                (DepartmentAgent.SEO, "seo_article"),
            ):
                auto = (
                    settings.cmo_auto_approve_smm
                    if agent == DepartmentAgent.SMM
                    else settings.cmo_auto_approve_seo
                )
                status = TaskStatus.APPROVED if auto and settings.cmo_mode != "review" else TaskStatus.PENDING_CMO_APPROVAL
                task = DepartmentTaskRecord(
                    agent=agent,
                    task_type=task_type,
                    priority=5,
                    status=status,
                    brief=default_brief[:500],
                    input_json={"strategy_summary": default_brief},
                )
                tasks.append(await db.create_task(task))

        return tasks
