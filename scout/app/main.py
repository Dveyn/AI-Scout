from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from scout.agent.runner import process_job
from scout.app.auth import (
    SESSION_KEY,
    AuthMiddleware,
    IPAllowlistMiddleware,
    auth_enabled,
    verify_credentials,
)
from scout.config import get_settings
from scout.company import (
    COMPANY_BRAND,
    COMPANY_CITY,
    COMPANY_SITE,
    DEFAULT_ICP,
    DEFAULT_OFFER,
    DEFAULT_PRESET,
    DEFAULT_PRODUCT,
    DEFAULT_QUERIES,
)
from scout.models.schemas import JobCreate, JobStatus
from scout.outreach.service import (
    build_job_report,
    mark_lead_sent_manual,
    prepare_outreach_channels,
    send_job_outreach,
    send_lead_outreach,
)
from scout.presets.loader import list_presets, load_preset
from scout.storage import db
from scout.storage import department_db as dept_db
from scout.department.models import AdCreativeStatus, DealStatus, DepartmentAgent, TaskStatus
from scout.app.system_status import system_warnings
from scout.app.department_labels import (
    deal_status_options,
    label_ad_status,
    label_agent,
    label_content_status,
    label_deal_status,
    label_platform,
    label_task_status,
    label_task_type,
    label_action,
)


class MessageEdit(BaseModel):
    subject: str | None = None
    message: str | None = None
    touch: int = 1

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["company_brand"] = COMPANY_BRAND
templates.env.globals["company_site"] = COMPANY_SITE
templates.env.globals["auth_enabled"] = auth_enabled
templates.env.globals["label_agent"] = label_agent
templates.env.globals["label_deal_status"] = label_deal_status
templates.env.globals["label_task_status"] = label_task_status
templates.env.globals["label_content_status"] = label_content_status
templates.env.globals["label_ad_status"] = label_ad_status
templates.env.globals["label_platform"] = label_platform
templates.env.globals["label_task_type"] = label_task_type
templates.env.globals["label_action"] = label_action
templates.env.globals["system_warnings"] = system_warnings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _form_defaults() -> dict:
    settings = get_settings()
    presets = []
    for name in list_presets():
        try:
            p = load_preset(name)
            presets.append(
                {
                    "name": name,
                    "label": p.get("label") or p.get("name", name),
                    "skill": p.get("skill", "outreach-writer"),
                    "query": p.get("query", ""),
                    "city": p.get("city", COMPANY_CITY),
                    "offer": p.get("offer", settings.default_offer or DEFAULT_OFFER),
                    "icp": p.get("icp", settings.default_icp or DEFAULT_ICP),
                    "product": p.get("product", settings.default_product or DEFAULT_PRODUCT),
                }
            )
        except (FileNotFoundError, ValueError):
            continue
    return {
        "offer": settings.default_offer or DEFAULT_OFFER,
        "icp": settings.default_icp or DEFAULT_ICP,
        "product": settings.default_product or DEFAULT_PRODUCT,
        "city": COMPANY_CITY,
        "queries": [{"query": q, "city": c} for q, c in DEFAULT_QUERIES],
        "presets": presets,
        "default_preset": settings.default_preset or DEFAULT_PRESET,
    }


def _secret_key() -> str:
    settings = get_settings()
    if settings.scout_secret_key:
        return settings.scout_secret_key
    # Локальная разработка без пароля — сессии не используются
    return "dev-only-insecure-key-change-on-server"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.auth_is_required() and not settings.scout_auth_password:
        raise RuntimeError("SCOUT_AUTH_PASSWORD обязателен при включённой авторизации")
    if settings.auth_is_required() and not settings.scout_secret_key:
        raise RuntimeError("SCOUT_SECRET_KEY обязателен при включённой авторизации")
    await db.init_db()
    yield


app = FastAPI(title="AI Scout", lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.add_middleware(IPAllowlistMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key(),
    session_cookie="scout_session",
    max_age=60 * 60 * 24 * 14,  # 14 дней
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "scout"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    if request.session.get(SESSION_KEY):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if verify_credentials(username, password):
        request.session[SESSION_KEY] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Неверный логин или пароль"},
        status_code=401,
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/logout")
async def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "job": None,
            "leads": [],
            "report": None,
            "defaults": _form_defaults(),
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    stats = await db.get_dashboard_stats()
    jobs = await db.list_jobs(limit=20)
    outreach = await db.list_outreach_log(limit=50)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"stats": stats, "jobs": jobs, "outreach": outreach},
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    leads = await db.list_leads(job_id)
    report = await db.get_job_report(job_id) or await build_job_report(job_id)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"job": job, "leads": leads, "report": report},
    )


@app.get("/api/presets")
async def api_presets():
    return _form_defaults()["presets"]


@app.post("/api/jobs")
async def create_job(payload: JobCreate, background_tasks: BackgroundTasks):
    job = await db.create_job(payload)
    background_tasks.add_task(process_job, job.id)
    return {"id": job.id, "status": job.status}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}/leads")
async def get_leads(job_id: str):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return await db.list_leads(job_id)


@app.get("/api/dashboard/stats")
async def dashboard_stats():
    return await db.get_dashboard_stats()


@app.get("/api/outreach/history")
async def outreach_history(limit: int = 100):
    return await db.list_outreach_log(limit=limit)


@app.post("/api/jobs/{job_id}/send")
async def send_job_emails(job_id: str, force: bool = False, touch: int = 1):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    report = await send_job_outreach(job_id, force=force, touch=touch)
    return report


@app.patch("/api/leads/{lead_id}/message")
async def edit_lead_message(lead_id: str, payload: MessageEdit):
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if payload.touch == 1:
        if not lead.result:
            raise HTTPException(400, "У лида нет результата для редактирования")
        lead.result = lead.result.model_copy(
            update={"subject": payload.subject, "message": payload.message}
        )
    else:
        updated = False
        new_followups = []
        for fu in lead.followups:
            if fu.touch == payload.touch:
                new_followups.append(
                    fu.model_copy(update={"subject": payload.subject, "message": payload.message or fu.message})
                )
                updated = True
            else:
                new_followups.append(fu)
        if not updated:
            raise HTTPException(400, f"Касание {payload.touch} не найдено")
        lead.followups = new_followups
    lead = await prepare_outreach_channels(lead, touch=payload.touch)
    await db.update_lead_result(lead)
    return {"ok": True, "id": lead.id}


@app.post("/api/leads/{lead_id}/mark-sent")
async def mark_lead_sent(lead_id: str, channel: str = "manual", touch: int = 1):
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    updated = await mark_lead_sent_manual(lead_id, channel=channel, touch=touch)
    return {"id": updated.id, "send_status": updated.send_status}


@app.post("/api/leads/{lead_id}/send")
async def send_lead_email(lead_id: str, force: bool = False, touch: int = 1):
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    updated = await send_lead_outreach(lead_id, force=force, touch=touch)
    return {"id": updated.id, "send_status": updated.send_status, "error": updated.send_error}


@app.get("/api/jobs/{job_id}/export.csv")
async def export_csv(job_id: str):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    leads = await db.list_leads(job_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "company",
            "category",
            "phone",
            "email",
            "telegram",
            "vk",
            "max",
            "lpr_name",
            "website",
            "website_quality_score",
            "website_issues",
            "address",
            "fit_score",
            "is_target",
            "pains",
            "subject",
            "message",
            "channel_hint",
            "send_status",
            "sent_at",
            "send_error",
            "fallback_whatsapp",
            "outreach_links",
            "followup_2_subject",
            "followup_2_message",
            "followup_3_subject",
            "followup_3_message",
            "reasoning_summary",
            "maps_url",
        ]
    )
    for lead in leads:
        r = lead.result
        audit = lead.website_audit or {}
        contacts = lead.contacts
        channel_links = "; ".join(f"{c.channel}:{c.url}" for c in lead.outreach_channels)
        fu2 = next((f for f in lead.followups if f.touch == 2), None)
        fu3 = next((f for f in lead.followups if f.touch == 3), None)
        writer.writerow(
            [
                lead.raw.name,
                lead.raw.category or "",
                lead.raw.phone or "",
                lead.email or lead.raw.email or "",
                "; ".join(contacts.telegram) if contacts else "",
                "; ".join(contacts.vk) if contacts else "",
                "; ".join(contacts.max_links) if contacts else "",
                (contacts.lpr_name if contacts else "") or (r.lpr_name if r else "") or "",
                lead.raw.website or "",
                audit.get("quality_score", ""),
                "; ".join((r.website_issues if r else []) or audit.get("issues") or []),
                lead.raw.address or "",
                r.fit_score if r else "",
                r.is_target if r else "",
                "; ".join(r.pains) if r else "",
                r.subject or "" if r else "",
                r.message or "" if r else "",
                r.channel_hint if r else "",
                lead.send_status.value if lead.send_status else "",
                lead.sent_at.isoformat() if lead.sent_at else "",
                lead.send_error or "",
                lead.fallback_text or "",
                channel_links,
                fu2.subject if fu2 else "",
                fu2.message if fu2 else "",
                fu3.subject if fu3 else "",
                fu3.message if fu3 else "",
                r.reasoning_summary if r else "",
                lead.raw.maps_url or "",
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="scout-{job_id}.csv"'},
    )


# --- AI Marketing Department ---

@app.get("/department", response_class=HTMLResponse)
async def department_dashboard(request: Request):
    settings = get_settings()
    stats = await dept_db.get_department_stats()
    tasks = await dept_db.list_tasks(limit=20)
    report = stats.get("latest_report")
    mode_label = (
        "Умный режим: тяжёлые задачи в Cursor, GPTunnel только на письма"
        if settings.department_uses_cursor_llm()
        else "Локальный режим: все агенты через GPTunnel"
    )
    return templates.TemplateResponse(
        request,
        "department/index.html",
        {
            "stats": stats,
            "tasks": tasks,
            "report": report,
            "dept_section": "home",
            "mode_label": mode_label,
        },
    )


@app.get("/department/deals", response_class=HTMLResponse)
async def department_deals(request: Request):
    deals = await dept_db.list_deals(limit=100)
    return templates.TemplateResponse(
        request,
        "department/deals.html",
        {
            "deals": deals,
            "deal_statuses": deal_status_options(),
            "dept_section": "deals",
        },
    )


@app.post("/department/deals/{deal_id}/status")
async def department_deal_status(deal_id: str, status: str = Form(...)):
    try:
        await dept_db.update_deal_status(deal_id, DealStatus(status))
    except ValueError:
        raise HTTPException(400, "Неверный статус сделки")
    return RedirectResponse("/department/deals", status_code=303)


@app.get("/department/deals/{deal_id}/proposal")
async def department_deal_proposal(deal_id: str):
    from scout.department.agents.sales import SalesAgent

    agent = SalesAgent()
    await agent.generate_proposal(deal_id)
    return RedirectResponse("/department/deals", status_code=303)


@app.get("/department/cmo", response_class=HTMLResponse)
async def department_cmo(request: Request):
    tasks = await dept_db.list_tasks(status=TaskStatus.PENDING_CMO_APPROVAL)
    return templates.TemplateResponse(
        request, "department/cmo.html", {"tasks": tasks, "dept_section": "cmo"}
    )


@app.post("/department/tasks/{task_id}/approve")
async def department_task_approve(task_id: str):
    await dept_db.approve_task(task_id)
    return RedirectResponse("/department/cmo", status_code=303)


@app.post("/department/tasks/{task_id}/reject")
async def department_task_reject(task_id: str):
    await dept_db.reject_task(task_id)
    return RedirectResponse("/department/cmo", status_code=303)


@app.get("/department/content", response_class=HTMLResponse)
async def department_content(request: Request):
    posts = await dept_db.list_content_posts(limit=50)
    return templates.TemplateResponse(
        request, "department/content.html", {"posts": posts, "dept_section": "content"}
    )


@app.get("/department/ads", response_class=HTMLResponse)
async def department_ads(request: Request):
    creatives = await dept_db.list_ad_creatives(limit=50)
    return templates.TemplateResponse(
        request, "department/ads.html", {"creatives": creatives, "dept_section": "ads"}
    )


@app.post("/department/ads/{creative_id}/approve")
async def department_ad_approve(creative_id: str):
    await dept_db.update_ad_creative_status(creative_id, AdCreativeStatus.APPROVED)
    return RedirectResponse("/department/ads", status_code=303)


@app.post("/department/ads/{creative_id}/reject")
async def department_ad_reject(creative_id: str):
    await dept_db.update_ad_creative_status(creative_id, AdCreativeStatus.REJECTED)
    return RedirectResponse("/department/ads", status_code=303)


@app.get("/department/logs", response_class=HTMLResponse)
async def department_logs(request: Request, agent: str | None = None):
    logs = await dept_db.list_agent_logs(agent=agent, limit=100)
    return templates.TemplateResponse(
        request,
        "department/logs.html",
        {
            "logs": logs,
            "filter_agent": agent,
            "agents": [a.value for a in DepartmentAgent],
            "dept_section": "logs",
        },
    )


@app.get("/jobs/{job_id}/fragment", response_class=HTMLResponse)
async def job_fragment(request: Request, job_id: str):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    leads = await db.list_leads(job_id)
    report = await db.get_job_report(job_id) or await build_job_report(job_id)
    polling = job.status not in (JobStatus.DONE, JobStatus.FAILED)
    return templates.TemplateResponse(
        request,
        "partials/job_panel.html",
        {
            "job": job,
            "leads": leads,
            "report": report,
            "polling": polling,
        },
    )
