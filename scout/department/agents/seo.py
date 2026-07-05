from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from scout.config import SCOUT_ROOT
from scout.department.base_agent import BaseAgent
from scout.department.models import (
    ContentPostRecord,
    ContentStatus,
    DepartmentTaskRecord,
    TaskStatus,
)
from scout.storage import department_db as db

logger = logging.getLogger(__name__)
CONTENT_DIR = SCOUT_ROOT / "data" / "content"


class SEOAgent(BaseAgent):
    agent_name = "seo"

    async def execute_task(self, task: DepartmentTaskRecord) -> list[ContentPostRecord]:
        prompt = (
            f"Задача от CMO:\n{task.brief}\n\n"
            f"Контекст: {task.input_json}\n\n"
            f"Подбери ключи и напиши 1 SEO-статью для B2B веб-студии."
        )
        result, _, _ = await self.run(prompt, action="seo_content")
        posts: list[ContentPostRecord] = []

        for article in result.get("articles", []):
            post = ContentPostRecord(
                task_id=task.id,
                platform="seo",
                title=str(article.get("title", "")),
                body=str(article.get("body_markdown", "")),
                status=ContentStatus.SCHEDULED,
            )
            posts.append(await db.create_content_post(post))

        if not posts and result.get("body_markdown"):
            posts.append(
                await db.create_content_post(
                    ContentPostRecord(
                        task_id=task.id,
                        platform="seo",
                        title=str(result.get("title", "SEO article")),
                        body=str(result.get("body_markdown", "")),
                        status=ContentStatus.SCHEDULED,
                    )
                )
            )

        task.status = TaskStatus.DONE
        task.completed_at = datetime.utcnow()
        await db.update_task(task)
        return posts

    async def publish_post(self, post: ContentPostRecord) -> bool:
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        slug = post.title.lower().replace(" ", "-")[:60] or post.id[:8]
        path = CONTENT_DIR / f"{slug}.md"
        meta = f"---\ntitle: {post.title}\nplatform: seo\n---\n\n"
        path.write_text(meta + post.body, encoding="utf-8")
        await db.update_content_status(post.id, ContentStatus.PUBLISHED)
        return True
