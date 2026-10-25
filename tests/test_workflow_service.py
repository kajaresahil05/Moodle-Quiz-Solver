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


def test_extract_moodle_base_url():
    """Verify base URL extraction from various Moodle URL patterns."""
    from app.services.browser_service import extract_moodle_base_url

    url1 = "https://elearn.apsit.edu.in/moodle/mod/quiz/attempt.php?attempt=185413&cmid=75000"
    assert extract_moodle_base_url(url1) == "https://elearn.apsit.edu.in/moodle"

    url2 = "https://elearn.apsit.edu.in/moodle/enrol/index.php?id=1495"
    assert extract_moodle_base_url(url2) == "https://elearn.apsit.edu.in/moodle"

    url3 = "https://moodle.college.edu/mod/quiz/view.php?id=123"
    assert extract_moodle_base_url(url3) == "https://moodle.college.edu"


@pytest.mark.asyncio
async def test_run_workflow_pre_authenticates_with_user_credentials():
    """Verify that _run_workflow pre-authenticates the user before navigating to the quiz."""
    from app.services import browser_service

    request = WorkflowCreate(
        quiz_url="https://elearn.apsit.edu.in/moodle/mod/quiz/attempt.php?attempt=185413&cmid=75000",
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
    mock_page.url = "https://elearn.apsit.edu.in/moodle/mod/quiz/attempt.php?attempt=185413&cmid=75000"
    mock_page.inner_text = AsyncMock(return_value="")

    ensure_login_mock = AsyncMock(return_value=True)

    with patch("app.services.workflow_service.browser_service.get_active_page", AsyncMock(return_value=mock_page)), \
         patch("app.services.workflow_service.browser_service.ensure_moodle_login", ensure_login_mock), \
         patch("app.services.workflow_service.browser_service.navigate_to", AsyncMock()), \
         patch("app.services.workflow_service.browser_service.check_login_required", AsyncMock(return_value=False)), \
         patch("app.services.workflow_service.browser_service.check_and_handle_course_enrolment", AsyncMock(return_value=False)), \
         patch("app.services.workflow_service.browser_service.check_and_start_attempt_if_view_page", AsyncMock()), \
         patch("app.services.workflow_service.browser_service.check_and_launch_secure_window_if_prompted", AsyncMock()), \
         patch("app.services.workflow_service.browser_service.check_is_moodle_quiz", AsyncMock(return_value=True)), \
         patch("app.services.workflow_service.QuizParser.extract_current_page_questions", AsyncMock(return_value=[])), \
         patch("app.services.workflow_service.browser_service.click_next_page", AsyncMock(return_value=False)), \
         patch("app.services.workflow_service.browser_service.click_finish_attempt", AsyncMock(return_value=True)), \
         patch("app.services.workflow_service.notif.notify_workflow_started", AsyncMock()), \
         patch("app.services.workflow_service.notif.notify_workflow_completed", AsyncMock()), \
         patch("app.services.workflow_service.notif.notify_workflow_error", AsyncMock()):

        await workflow_service._run_workflow(
            workflow_id=workflow_id,
            request=request,
            moodle_username="23104171",
            moodle_password="mypassword",
        )

    # ensure_moodle_login must be called with the student's credentials
    ensure_login_mock.assert_called_once_with(
        "23104171", "mypassword", request.quiz_url, mock_page
    )
