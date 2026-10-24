"""
app/routes/auth.py
Authentication routes: login, logout, and user session verification.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["authentication"])
templates = Jinja2Templates(directory="templates")


class LoginRequest(BaseModel):
    moodle_id: str
    password: str
    remember: bool = False


# ─── HTML Routes ────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, next: Optional[str] = "/"):
    """Render login page for user authentication."""
    user = auth_service.get_current_user(request)
    if user:
        return RedirectResponse(url=next or "/", status_code=status.HTTP_303_SEE_OTHER)

    logged_out = request.query_params.get("logged_out") == "1"
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next_url": next or "/",
            "logged_out": logged_out,
            "error": None,
        },
    )


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_submit(
    request: Request,
    moodle_id: str = Form(""),
    password: str = Form(""),
    remember: bool = Form(False),
    next: Optional[str] = Form("/"),
):
    """Handle standard HTML form submission for login."""
    moodle_id = moodle_id.strip()
    if not moodle_id or not password:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "next_url": next or "/",
                "error": "Please enter both your Moodle ID and Password.",
                "moodle_id": moodle_id,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token = auth_service.create_user_session(moodle_id, password)
        redirect_url = next if (next and next.startswith("/") and not next.startswith("//")) else "/"
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
        
        max_age = auth_service.COOKIE_MAX_AGE if remember else None
        response.set_cookie(
            key=auth_service.COOKIE_NAME,
            value=token,
            max_age=max_age,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response
    except Exception as e:
        logger.error("Login failed: %s", e)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "next_url": next or "/",
                "error": "Failed to create session. Please try again.",
                "moodle_id": moodle_id,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/logout", response_class=HTMLResponse, include_in_schema=False)
@router.post("/logout", response_class=HTMLResponse, include_in_schema=False)
async def logout(request: Request):
    """Log out the current user and redirect to login page."""
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if token:
        auth_service.terminate_user_session(token)

    response = RedirectResponse(url="/login?logged_out=1", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=auth_service.COOKIE_NAME, path="/")
    return response


# ─── API Routes ─────────────────────────────────────────────────────────────

@router.post("/api/auth/login")
async def api_login(payload: LoginRequest, response: Response):
    """API endpoint to log in and receive an authentication session."""
    moodle_id = payload.moodle_id.strip()
    if not moodle_id or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Moodle ID and Password are both required.",
        )

    token = auth_service.create_user_session(moodle_id, payload.password)
    max_age = auth_service.COOKIE_MAX_AGE if payload.remember else None
    response.set_cookie(
        key=auth_service.COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {
        "success": True,
        "moodle_id": moodle_id,
        "token": token,
        "message": f"Successfully logged in as {moodle_id}",
    }


@router.post("/api/auth/logout")
async def api_logout(request: Request, response: Response):
    """API endpoint to terminate current session."""
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if token:
        auth_service.terminate_user_session(token)
    response.delete_cookie(key=auth_service.COOKIE_NAME, path="/")
    return {"success": True, "message": "Successfully logged out"}


@router.get("/api/auth/me")
async def api_me(request: Request):
    """Get current authenticated user info (without password)."""
    user = auth_service.get_current_user(request)
    if not user:
        return {"authenticated": False, "moodle_id": None}
    return {
        "authenticated": True,
        "moodle_id": user.get("moodle_id"),
        "created_at": user.get("created_at"),
        "last_active": user.get("last_active"),
    }
