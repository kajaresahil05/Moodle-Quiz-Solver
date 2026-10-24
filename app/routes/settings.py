"""
app/routes/settings.py
API routes for settings and system health.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.services.gemini_service import GeminiService
from app.services import notification_service as notif

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["settings"])

_gemini = GeminiService()


class HealthResponse(BaseModel):
    status: str
    gemini_configured: bool
    gemini_model: str
    database_ok: bool
    version: str = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check endpoint."""
    settings = get_settings()
    db_ok = True
    try:
        from app import database as db
        db.list_workflows(limit=1)
    except Exception:
        db_ok = False

    return HealthResponse(
        status="ok",
        gemini_configured=settings.gemini_configured,
        gemini_model=settings.gemini_model,
        database_ok=db_ok,
    )


@router.post("/test-gemini")
async def test_gemini():
    """Test Gemini API connectivity."""
    try:
        ok, msg = await _gemini.test_connection_detailed()
        return {"success": ok, "message": msg}
    except RuntimeError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": f"Unexpected error: {str(e)[:200]}"}


@router.post("/test-groq")
async def test_groq():
    """Test Groq API connectivity."""
    try:
        ok, msg = await _gemini.test_groq()
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": f"Groq test failed: {str(e)[:200]}"}


@router.post("/test-ollama")
async def test_ollama():
    """Test Ollama local connectivity."""
    try:
        ok, msg = await _gemini.test_ollama()
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": f"Ollama test failed: {str(e)[:200]}"}


@router.get("/notifications")
async def get_notifications(
    workflow_id: str = None,
    unread_only: bool = False,
    limit: int = 50,
):
    """Get notifications for the dashboard."""
    return {
        "notifications": notif.get_notifications(
            workflow_id=workflow_id,
            unread_only=unread_only,
            limit=min(limit, 100),
        )
    }


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """Mark a notification as read."""
    ok = notif.mark_read(notification_id)
    return {"success": ok}


@router.post("/notifications/mark-all-read")
async def mark_all_notifications_read(workflow_id: str = None):
    """Mark all notifications as read."""
    count = notif.mark_all_read(workflow_id=workflow_id)
    return {"success": True, "marked": count}
