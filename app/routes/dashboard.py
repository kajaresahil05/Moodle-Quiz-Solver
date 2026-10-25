"""
app/routes/dashboard.py
Dashboard HTML routes - serves the web UI.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import database as db
from app.services import auth_service
from app.services import notification_service as notif

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """Main dashboard page."""
    user = auth_service.get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    moodle_id = user.get("moodle_id", "")
    workflows = db.list_workflows(user_id=moodle_id if moodle_id else None, limit=20)
    user_workflow_ids = {w.workflow_id for w in workflows}
    all_notifs = notif.get_notifications(unread_only=False, limit=50)
    notifications = [n for n in all_notifs if n.get("workflow_id") in user_workflow_ids][:10]
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": user,
            "workflows": workflows,
            "notifications": notifications,
            "unread_count": sum(1 for n in notifications if not n["read"]),
        },
    )


@router.get("/workflow/{workflow_id}", response_class=HTMLResponse, include_in_schema=False)
async def workflow_detail(request: Request, workflow_id: str):
    """Workflow detail page."""
    user = auth_service.get_current_user(request)
    if not user:
        return RedirectResponse(url=f"/login?next=/workflow/{workflow_id}", status_code=status.HTTP_303_SEE_OTHER)

    workflow = db.get_workflow(workflow_id)
    if not workflow or (workflow.user_id and user.get("moodle_id") and workflow.user_id != user.get("moodle_id")):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "current_user": user, "message": "Workflow not found"},
            status_code=404,
        )
    questions = db.list_question_records(workflow_id)
    events = db.list_events(workflow_id, limit=50)
    notifications = notif.get_notifications(workflow_id=workflow_id)
    return templates.TemplateResponse(
        "workflow_detail.html",
        {
            "request": request,
            "current_user": user,
            "workflow": workflow,
            "questions": questions,
            "events": events,
            "notifications": notifications,
        },
    )


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(request: Request):
    """Settings page."""
    user = auth_service.get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=/settings", status_code=status.HTTP_303_SEE_OTHER)

    from app.config import get_settings
    settings = get_settings()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "current_user": user,
            "gemini_configured": settings.gemini_configured,
            "gemini_model": settings.gemini_model,
            "groq_configured": settings.groq_configured,
            "groq_model": settings.groq_model,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "browser_headless": settings.browser_headless,
        },
    )
