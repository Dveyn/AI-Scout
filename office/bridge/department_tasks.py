from __future__ import annotations

import logging
from typing import Any

from scout.department.models import DepartmentAgent, DepartmentTaskRecord, TaskStatus
from scout.storage import department_db as dept_db

logger = logging.getLogger(__name__)

AGENT_MAP = {
    "marketing": DepartmentAgent.CMO,
    "smm": DepartmentAgent.SMM,
    "seo": DepartmentAgent.SEO,
    "ads": DepartmentAgent.ADS,
    "targetologist": DepartmentAgent.ADS,
    "sales": DepartmentAgent.SALES,
    "analytics": DepartmentAgent.ANALYTICS,
}


async def create_department_task(
    *,
    agent_key: str,
    task_type: str,
    brief: str,
    priority: int = 5,
    requires_approval: bool = False,
    input_json: dict[str, Any] | None = None,
) -> DepartmentTaskRecord:
    agent = AGENT_MAP.get(agent_key, DepartmentAgent.CMO)
    task = DepartmentTaskRecord(
        agent=agent,
        task_type=task_type,
        priority=priority,
        status=TaskStatus.PENDING_CMO_APPROVAL if requires_approval else TaskStatus.APPROVED,
        brief=brief,
        input_json=input_json or {},
        requires_approval=requires_approval,
    )
    return await dept_db.create_task(task)


async def list_active_tasks(limit: int = 30) -> list[DepartmentTaskRecord]:
    tasks = await dept_db.list_tasks(limit=limit)
    active_statuses = {
        TaskStatus.PENDING,
        TaskStatus.PENDING_CMO_APPROVAL,
        TaskStatus.APPROVED,
        TaskStatus.IN_PROGRESS,
    }
    return [t for t in tasks if t.status in active_statuses]


async def list_recent_agent_logs(limit: int = 50) -> list[dict[str, Any]]:
    logs = await dept_db.list_agent_logs(limit=limit)
    return [log.model_dump() for log in logs]
