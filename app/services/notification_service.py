"""
app/services/notification_service.py
Handles desktop and in-dashboard notifications for workflow events.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory notification queue for dashboard polling
_notifications: List[Dict[str, Any]] = []
_max_notifications = 200


def _add_notification(
    workflow_id: str,
    title: str,
    message: str,
    level: str = "info",  # info | success | warning | error
) -> Dict[str, Any]:
    """Add a notification to the in-memory queue."""
    notification = {
        "id": f"notif_{int(datetime.utcnow().timestamp() * 1000)}",
        "workflow_id": workflow_id,
        "title": title,
        "message": message,
        "level": level,
        "timestamp": datetime.utcnow().isoformat(),
        "read": False,
    }
    _notifications.insert(0, notification)
    # Keep queue bounded
    if len(_notifications) > _max_notifications:
        _notifications.pop()
    return notification


def get_notifications(
    workflow_id: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Get notifications, optionally filtered by workflow."""
    result = _notifications
    if workflow_id:
        result = [n for n in result if n["workflow_id"] == workflow_id]
    if unread_only:
        result = [n for n in result if not n["read"]]
    return result[:limit]


def mark_read(notification_id: str) -> bool:
    """Mark a notification as read."""
    for n in _notifications:
        if n["id"] == notification_id:
            n["read"] = True
            return True
    return False


def mark_all_read(workflow_id: Optional[str] = None) -> int:
    """Mark all (or workflow-specific) notifications as read."""
    count = 0
    for n in _notifications:
        if not n["read"]:
            if workflow_id is None or n["workflow_id"] == workflow_id:
                n["read"] = True
                count += 1
    return count


async def notify_workflow_started(workflow_id: str, quiz_url: str) -> None:
    """Notify that a workflow has started."""
    msg = f"Workflow {workflow_id[:8]} started for quiz"
    _add_notification(workflow_id, "Workflow Started", msg, "info")
    await _try_desktop_notification("Moodle Quiz Assistant", msg)


async def notify_workflow_completed(workflow_id: str, answered: int, total: int) -> None:
    """Notify that a workflow has completed."""
    msg = f"Completed: {answered}/{total} questions answered. Workflow {workflow_id[:8]}"
    _add_notification(workflow_id, "Workflow Completed", msg, "success")
    await _try_desktop_notification("Quiz Assistant ✓", msg)


async def notify_submission_verified(workflow_id: str) -> None:
    """Notify that quiz submission was verified by Moodle."""
    msg = f"Quiz submitted and verified by Moodle. Workflow {workflow_id[:8]}"
    _add_notification(workflow_id, "Quiz Submitted", msg, "success")
    await _try_desktop_notification("Quiz Submitted ✓", msg)


async def notify_login_required(workflow_id: str) -> None:
    """Notify that login is required."""
    msg = f"Login required. Please log in to Moodle and restart. Workflow {workflow_id[:8]}"
    _add_notification(workflow_id, "Login Required", msg, "warning")
    await _try_desktop_notification("Login Required", msg)


async def notify_api_error(workflow_id: str, error: str) -> None:
    """Notify about an API error."""
    msg = f"Gemini API error in workflow {workflow_id[:8]}: {error[:100]}"
    _add_notification(workflow_id, "API Error", msg, "error")
    await _try_desktop_notification("Quiz Assistant Error", msg)


async def notify_manual_review(workflow_id: str, question_id: str, reason: str) -> None:
    """Notify that a question needs manual review."""
    msg = f"Question {question_id} needs manual review: {reason[:100]}"
    _add_notification(workflow_id, "Manual Review Required", msg, "warning")
    await _try_desktop_notification("Review Required", msg)


async def notify_workflow_error(workflow_id: str, error: str) -> None:
    """Notify about a workflow error."""
    msg = f"Workflow {workflow_id[:8]} failed: {error[:150]}"
    _add_notification(workflow_id, "Workflow Failed", msg, "error")
    await _try_desktop_notification("Workflow Failed", msg)


async def _try_desktop_notification(title: str, message: str) -> None:
    """Attempt to show a desktop notification without ever blocking the workflow."""
    try:
        import threading
        t = threading.Thread(
            target=_show_desktop_notification,
            args=(title, message),
            daemon=True,
            name="desktop_notif",
        )
        t.start()
    except Exception:
        pass  # Dashboard notification is always recorded


def _show_desktop_notification(title: str, message: str) -> None:
    """Synchronous desktop notification attempt, prioritized for non-blocking libraries."""
    try:
        from plyer import notification as plyer_notif
        plyer_notif.notify(
            title=title,
            message=message,
            app_name="Moodle Quiz Assistant",
            timeout=3,
        )
        return
    except Exception as e:
        logger.debug("plyer notification failed: %s", e)

    try:
        from win11toast import toast
        toast(title, message)
        return
    except Exception as e:
        logger.debug("win11toast failed: %s", e)
