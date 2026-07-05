from __future__ import annotations

import logging
from typing import Any

from office.bridge.cursor_handoff import export_heavy_work_to_cursor
from office.bridge.department_tasks import create_department_task
from office.config import get_office_settings
from office.llm import OfficeLLMClient, OfficeLLMError, can_spend_office
from office.models import AgentStatus, ModelTier
from office.registry.prompts import build_agent_system_prompt
from office.storage import db as office_db

logger = logging.getLogger(__name__)


def _human_summary(result: dict[str, Any]) -> str:
    if result.get("error"):
        return f"Ошибка: {result['error']}"
    if result.get("summary"):
        return str(result["summary"])[:1500]
    if result.get("mode") == "cursor":
        tid = result.get("task_id", "")
        return (
            "Задача поставлена в очередь маркетинга (Cursor). "
            f"ID: {tid[:8]}… — результат появится в /department после обработки."
        )
    return "Задача выполнена."


async def _set_ws(
    ws_id: str,
    *,
    status: AgentStatus,
    current_task: str = "",
    last_result: str = "",
) -> None:
    ws = await office_db.get_workstation(ws_id)
    if not ws:
        return
    ws.status = status
    ws.current_task = current_task
    if last_result:
        ws.last_result = last_result
    await office_db.save_workstation(ws)


async def run_marketing_crew(brief: str) -> dict[str, Any]:
    """Sequential marketing crew: CMO plans → SMM/Ads execute via scout adapters."""
    from office.crews.runner import CrewAgent, CrewRunner, CrewTask

    async def cmo_handler(prompt: str, state: dict[str, Any]) -> dict[str, Any]:
        result = await execute_marketing_brief(prompt, task_type="marketing_crew", force_local=True)
        return {
            "summary": result.get("summary", ""),
            "cost_rub": result.get("cost_rub", 0),
            "mode": result.get("mode"),
            "tasks": result.get("tasks_created", []),
        }

    cmo = CrewAgent(
        role="CMO",
        goal="Сформировать маркетинговый план",
        backstory="Руководитель маркетинга B2B веб-студии",
        tier=ModelTier.STRATEGY,
        department="marketing",
        handler=cmo_handler,
    )
    crew = CrewRunner(
        agents=[cmo],
        tasks=[CrewTask(description=brief, agent=cmo)],
    )
    result = await crew.kickoff({"brief": brief})
    return {
        "summary": result.summary,
        "outputs": result.outputs,
        "cost_rub": result.total_cost_rub,
    }


async def execute_marketing_brief(
    brief: str,
    *,
    task_type: str = "marketing_crew",
    force_local: bool = False,
) -> dict[str, Any]:
    """Marketing crew: plan via CMO logic, delegate to scout department agents."""
    settings = get_office_settings()
    cost = 0.0
    use_cursor = (settings.uses_hybrid() or settings.uses_cursor()) and not force_local

    if use_cursor:
        task = await create_department_task(
            agent_key="cmo",
            task_type=task_type,
            brief=brief,
            priority=8,
            requires_approval=True,
            input_json={"source": "office_marketing_crew"},
        )
        handoff = await export_heavy_work_to_cursor(
            "marketing_task",
            {"task_id": task.id, "brief": brief, "agent": "cmo"},
        )
        return {
            "mode": "cursor",
            "task_id": task.id,
            "handoff_file": handoff,
            "cost_rub": 0.0,
            "summary": (
                "Задача в очереди Cursor Automations. "
                "Откройте http://localhost:8080/department — там появится задача CMO."
            ),
        }

    if not await can_spend_office(department="marketing"):
        return {"error": "Бюджет LLM исчерпан (лимит в scout/.env LLM_DAILY_BUDGET_RUB)", "cost_rub": 0.0}

    from scout.department.agents.cmo import CMOAgent
    from scout.department.agents.smm import SMMAgent
    from scout.department.models import DepartmentTaskRecord, TaskStatus

    cmo = CMOAgent()
    try:
        result, summary, cmo_cost = await cmo.run(
            f"Составь план маркетинговых задач на основе брифа CEO:\n{brief}",
            action="office_marketing_plan",
        )
    except Exception as exc:
        logger.exception("CMO run failed")
        return {"error": f"GPTunnel: {exc}", "cost_rub": 0.0}
    cost += cmo_cost

    tasks_created: list[str] = []
    planned = result.get("tasks") or result.get("planned_tasks") or []
    if isinstance(planned, list) and planned:
        for item in planned[:4]:
            if isinstance(item, dict):
                agent_key = str(item.get("agent", "smm")).lower()
                task = await create_department_task(
                    agent_key=agent_key,
                    task_type=str(item.get("type", "content")),
                    brief=str(item.get("brief", brief))[:2000],
                    priority=int(item.get("priority", 6)),
                    requires_approval=agent_key in ("ads", "smm"),
                )
                tasks_created.append(task.id)
                if task.status.value == "approved" and agent_key == "smm":
                    smm = SMMAgent()
                    dept_task = DepartmentTaskRecord(
                        id=task.id,
                        agent=task.agent,
                        task_type=task.task_type,
                        brief=task.brief,
                        status=TaskStatus.APPROVED,
                    )
                    await smm.execute_task(dept_task)
    else:
        task = await create_department_task(
            agent_key="smm",
            task_type=task_type,
            brief=brief,
            priority=7,
            requires_approval=True,
        )
        tasks_created.append(task.id)

    return {
        "mode": "local",
        "summary": summary or "CMO составил план, задачи созданы в маркетинговом отделе.",
        "tasks_created": tasks_created,
        "cmo_plan": result,
        "cost_rub": cost,
    }


async def run_workstation_task(workstation_id: str, brief: str) -> dict[str, Any]:
    ws = await office_db.get_workstation(workstation_id)
    if not ws:
        return {"error": "workstation not found"}

    await office_db.log_activity(workstation_id, "start", f"Задача: {brief[:300]}")
    await _set_ws(workstation_id, status=AgentStatus.WORKING, current_task=brief[:200])

    try:
        if ws.preset_id == "coo":
            from office.orchestrator.directive import run_directive

            await office_db.log_activity(
                workstation_id, "run", "COO: декомпозиция и запуск отделов"
            )
            directive = await run_directive(brief)
            summary = directive.final_report or directive.coo_plan or "Готово"
            await _set_ws(
                workstation_id,
                status=AgentStatus.DONE,
                current_task=brief[:200],
                last_result=summary[:1500],
            )
            await office_db.log_activity(workstation_id, "done", summary[:500])
            return {
                "workstation_id": ws.id,
                "mode": "directive",
                "summary": summary,
                "coo_plan": directive.coo_plan,
                "dept_results": directive.dept_results,
                "directive_id": directive.id,
                "cost_rub": directive.cost_rub,
            }

        if ws.preset_id == "executive_assistant":
            from office.crews.secretary import run_secretary_task

            return await run_secretary_task(workstation_id, brief)

        if ws.department_slug == "marketing":
            await office_db.log_activity(workstation_id, "run", "Запуск через маркетинг (GPTunnel локально)")
            result = await execute_marketing_brief(
                brief, task_type=f"ws_{ws.preset_id}", force_local=True
            )
        else:
            if not await can_spend_office(department=ws.department_slug):
                await office_db.log_activity(workstation_id, "error", "Бюджет LLM исчерпан")
                await _set_ws(workstation_id, status=AgentStatus.BLOCKED, current_task=brief[:200])
                return {"error": "Бюджет LLM исчерпан. Проверьте LLM_DAILY_BUDGET_RUB в scout/.env"}

            await office_db.log_activity(workstation_id, "llm", f"Запрос GPTunnel ({ws.model_tier.value})")
            llm = OfficeLLMClient()
            prompt = f"{build_agent_system_prompt(ws)}\n\nЗадача CEO:\n{brief}"
            try:
                resp = await llm.complete(
                    ws.role,
                    prompt,
                    tier=ws.model_tier,
                    department=ws.department_slug,
                )
            except OfficeLLMError as exc:
                await office_db.log_activity(workstation_id, "error", str(exc))
                await _set_ws(
                    workstation_id,
                    status=AgentStatus.BLOCKED,
                    current_task=brief[:200],
                    last_result=str(exc),
                )
                return {"error": str(exc)}

            if resp.content.startswith("Бюджет LLM"):
                result = {"error": resp.content, "cost_rub": 0}
            else:
                result = {"summary": resp.content, "cost_rub": resp.cost_rub, "mode": "local"}
                await office_db.log_activity(
                    workstation_id, "done", resp.content[:500]
                )

        if result.get("error"):
            await _set_ws(
                workstation_id,
                status=AgentStatus.BLOCKED,
                current_task=brief[:200],
                last_result=result["error"],
            )
            await office_db.log_activity(workstation_id, "error", result["error"])
        elif result.get("mode") == "cursor":
            summary = _human_summary(result)
            await office_db.log_activity(workstation_id, "queue", summary)
            await _set_ws(
                workstation_id,
                status=AgentStatus.WAITING_APPROVAL,
                current_task=brief[:200],
                last_result=summary,
            )
        else:
            summary = _human_summary(result)
            await office_db.log_activity(workstation_id, "done", summary[:500])
            await _set_ws(
                workstation_id,
                status=AgentStatus.DONE,
                current_task=brief[:200],
                last_result=summary,
            )

        return {"workstation_id": ws.id, "activity": "logged", **result}

    except Exception as exc:
        logger.exception("workstation task failed")
        msg = f"Сбой: {exc}"
        await office_db.log_activity(workstation_id, "error", msg)
        await _set_ws(
            workstation_id,
            status=AgentStatus.BLOCKED,
            current_task=brief[:200],
            last_result=msg,
        )
        return {"error": msg, "workstation_id": ws.id}
