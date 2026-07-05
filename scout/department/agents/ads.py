from __future__ import annotations

import logging
from datetime import datetime

from scout.department.base_agent import BaseAgent
from scout.department.models import (
    AdCreativeRecord,
    AdCreativeStatus,
    DepartmentTaskRecord,
    TaskStatus,
)
from scout.storage import department_db as db

logger = logging.getLogger(__name__)


class AdsAgent(BaseAgent):
    agent_name = "ads"

    async def execute_task(self, task: DepartmentTaskRecord) -> list[AdCreativeRecord]:
        prompt = (
            f"Задача от CMO:\n{task.brief}\n\n"
            f"Контекст: {task.input_json}\n\n"
            f"Создай 3 рекламных креатива с A/B гипотезами для Яндекс Директ / VK Ads."
        )
        result, _, _ = await self.run(prompt, action="ad_creatives")
        creatives: list[AdCreativeRecord] = []

        for item in result.get("creatives", []):
            creative = AdCreativeRecord(
                task_id=task.id,
                headlines=list(item.get("headlines", [])),
                body=str(item.get("body", "")),
                audience=str(item.get("audience", "")),
                ab_hypothesis=str(item.get("ab_hypothesis", "")),
                status=AdCreativeStatus.PENDING_APPROVAL,
            )
            creatives.append(await db.create_ad_creative(creative))

        if not creatives and result.get("body"):
            creatives.append(
                await db.create_ad_creative(
                    AdCreativeRecord(
                        task_id=task.id,
                        headlines=[str(result.get("headline", "B2B портал"))],
                        body=str(result.get("body", "")),
                        audience=str(result.get("audience", "B2B РФ")),
                        status=AdCreativeStatus.PENDING_APPROVAL,
                    )
                )
            )

        task.output_json = {
            "creatives_count": len(creatives),
            "budget": result.get("budget_recommendation", ""),
        }
        task.status = TaskStatus.DONE
        task.completed_at = datetime.utcnow()
        await db.update_task(task)
        return creatives
