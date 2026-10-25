"""
tests/test_workflow_service.py
Tests for workflow_service helper functions and execution safety.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import WorkflowCreate, WorkflowMode, WorkflowState
from app.services import workflow_service
from app import database as db


def test_workflow_url_cleaning_regex():
    """Test URL normalization logic including page parameter resetting."""
    test_url = '  "https://elearn.apsit.edu.in/moodle/mod/quiz/attempt.php?attempt=185399&cmid=71368&page=4#section1" '
    clean_url = test_url.strip().strip('"').strip("'")
    if "#" in clean_url:
        clean_url = clean_url.split("#")[0]
    if "/mod/quiz/attempt.php" in clean_url and "page=" in clean_url:
        clean_url = workflow_service.re.sub(r'([?&])page=\d+', r'\g<1>page=0', clean_url)

    assert "page=0" in clean_url
    assert "page=4" not in clean_url
    assert "#section1" not in clean_url
    assert clean_url.startswith("https://elearn.apsit.edu.in/")


def test_workflow_enrolment_regex():
    """Test regex extraction for course enrolment redirects."""
    enrol_url = "https://elearn.apsit.edu.in/moodle/enrol/index.php?id=1234"
    course_match = workflow_service.re.search(r'[?&]id=(\d+)', enrol_url)
    assert course_match is not None
    assert course_match.group(1) == "1234"

    enrol_url_param2 = "https://elearn.apsit.edu.in/moodle/enrol/index.php?foo=bar&id=5678"
    course_match2 = workflow_service.re.search(r'[?&]id=(\d+)', enrol_url_param2)
    assert course_match2 is not None
    assert course_match2.group(1) == "5678"


@pytest.mark.asyncio
async def test_run_workflow_handles_enrolment_without_name_error():
    """Verify _run_workflow handles redirect to enrol/index.php without NameError on 're'."""
    request = WorkflowCreate(
        quiz_url="https://elearn.apsit.edu.in/moodle/mod/quiz/attempt.php?attempt=185399&cmid=71368",
        mode=WorkflowMode.PRACTICE,
        auto_submit=False,
    )
    record = db.create_workflow(
        quiz_url=request.quiz_url,
        mode=request.mode.value,
        auto_submit=request.auto_submit,
    )
    workflow_id = record.workflow_id

    mock_page = MagicMock()
    mock_page.url = "https://elearn.apsit.edu.in/moodle/enrol/index.php?id=9999"
    mock_page.inner_text = AsyncMock(return_value="You cannot enrol yourself in this course.")

    with patch("app.services.workflow_service.browser_service.get_active_page", AsyncMock(return_value=mock_page)), \
         patch("app.services.workflow_service.browser_service.navigate_to", AsyncMock()), \
         patch("app.services.workflow_service.browser_service.check_login_required", AsyncMock(return_value=False)), \
         patch("app.services.workflow_service.browser_service.check_and_handle_course_enrolment", AsyncMock(return_value=False)), \
         patch("app.services.workflow_service.browser_service.check_and_start_attempt_if_view_page", AsyncMock()), \
         patch("app.services.workflow_service.browser_service.check_and_launch_secure_window_if_prompted", AsyncMock()), \
         patch("app.services.workflow_service.browser_service.check_is_moodle_quiz", AsyncMock(return_value=False)), \
         patch("app.services.workflow_service.notif.notify_workflow_started", AsyncMock()), \
         patch("app.services.workflow_service.notif.notify_workflow_completed", AsyncMock()), \
         patch("app.services.workflow_service.notif.notify_workflow_error", AsyncMock()):

        await workflow_service._run_workflow(
            workflow_id=workflow_id,
            request=request,
            moodle_username="",
            moodle_password="",
        )

    record = db.get_workflow(workflow_id)
    assert record is not None
    assert record.state == WorkflowState.FAILED
    assert "name 're' is not defined" not in (record.error_message or "")
    assert "Course enrolment required: Your Moodle account is not enrolled in Course #9999" in (record.error_message or "")
