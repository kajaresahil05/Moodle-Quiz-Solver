"""
app/services/auth_service.py
Authentication and session management service.
Allows multiple users to log in with their Moodle ID and Password.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status

from app import database as db
from app.config import get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "quiz_session"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def create_user_session(moodle_id: str, moodle_password: str) -> str:
    """Create a new session for a user and return the session token."""
    moodle_id = moodle_id.strip()
    if not moodle_id:
        raise ValueError("Moodle ID cannot be empty.")
    if not moodle_password:
        raise ValueError("Password cannot be empty.")

    token = secrets.token_urlsafe(32)
    db.save_session(session_token=token, moodle_id=moodle_id, moodle_password=moodle_password)
    logger.info("Created active session for Moodle ID: %s", moodle_id)
    return token


def terminate_user_session(session_token: str) -> None:
    """End a user session."""
    if session_token:
        db.delete_session(session_token)
        logger.info("Terminated session: %s", session_token[:8])


def get_current_user(request: Request) -> Optional[dict]:
    """
    Extract the current authenticated user from request cookie or header.
    Returns dict with keys: moodle_id, moodle_password, session_token.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        # Check Authorization header: Bearer <token>
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        session = db.get_session(token)
        if session:
            return session

    # Fallback to config only if explicitly provided in environment (e.g. testing)
    settings = get_settings()
    if settings.moodle_username and settings.moodle_password:
        return {
            "session_token": "env_fallback",
            "moodle_id": settings.moodle_username,
            "moodle_password": settings.moodle_password,
            "created_at": "",
            "last_active": "",
        }

    return None


def require_auth_user(request: Request) -> dict:
    """FastAPI dependency for endpoints that require an active session."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in with your Moodle credentials.",
        )
    return user
