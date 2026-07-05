from __future__ import annotations

import logging
from datetime import datetime

from scout.department.base_agent import BaseAgent
from scout.department.integrations.telegram_publisher import publish_telegram_channel
from scout.department.integrations.tenchat_draft import save_tenchat_draft
from scout.department.integrations.vk_publisher import publish_vk_post
from scout.department.models import ContentPostRecord, ContentStatus, DepartmentTaskRecord, TaskStatus
from scout.storage import department_db as db

logger = logging.getLogger(__name__)


class SMMAgent(BaseAgent):
    agent_name = "smm"

    async def execute_task(self, task: DepartmentTaskRecord) -> list[ContentPostRecord]:
        prompt = (
            f"Задача от CMO:\n{task.brief}\n\n"
            f"Контекст: {task.input_json}\n\n"
            f"Создай контент-план: 1 пост на VK, 1 на Telegram, 1 черновик TenChat."
        )
        result, _, _ = await self.run(prompt, action="content_plan")
        posts: list[ContentPostRecord] = []

        for item in result.get("posts", []):
            post = ContentPostRecord(
                task_id=task.id,
                platform=str(item.get("platform", "telegram")),
                title=str(item.get("title", "")),
                body=str(item.get("body", "")),
                status=ContentStatus.SCHEDULED,
            )
            posts.append(await db.create_content_post(post))

        if not posts and result.get("body"):
            posts.append(
                await db.create_content_post(
                    ContentPostRecord(
                        task_id=task.id,
                        platform="telegram",
                        body=str(result.get("body", "")),
                        status=ContentStatus.SCHEDULED,
                    )
                )
            )

        task.status = TaskStatus.DONE
        task.completed_at = datetime.utcnow()
        await db.update_task(task)
        return posts

    async def publish_post(self, post: ContentPostRecord) -> bool:
        platform = post.platform.lower()
        text = f"{post.title}\n\n{post.body}".strip() if post.title else post.body
        ok = False

        if platform == "vk":
            ok = await publish_vk_post(text)
        elif platform == "telegram":
            ok = await publish_telegram_channel(text)
        elif platform == "tenchat":
            ok = save_tenchat_draft(post.id, text)
            if ok:
                await db.update_content_status(post.id, ContentStatus.DRAFT)
                return True

        if ok:
            await db.update_content_status(post.id, ContentStatus.PUBLISHED, datetime.utcnow())
        else:
            await db.update_content_status(post.id, ContentStatus.FAILED)
        return ok
