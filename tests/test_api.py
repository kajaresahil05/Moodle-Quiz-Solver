"""
tests/test_api.py
Integration tests for FastAPI endpoints using TestClient.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create an authenticated test client for the FastAPI app."""
    from app.main import app
    from app.services import auth_service
    token = auth_service.create_user_session("test_student", "test_pass")
    with TestClient(app, raise_server_exceptions=False, cookies={auth_service.COOKIE_NAME: token}) as c:
        yield c


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "gemini_configured" in data
    assert "database_ok" in data


def test_list_workflows_empty(client):
    res = client.get("/api/workflows")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_create_workflow_invalid_url(client):
    res = client.post("/api/workflows", json={
        "quiz_url": "not-a-url",
        "mode": "practice",
        "auto_submit": False,
    })
    assert res.status_code == 422  # Validation error


def test_create_workflow_valid(client, monkeypatch):
    """Test workflow creation with mocked browser."""
    # Mock the workflow start to avoid actual browser launch
    import asyncio
    from app.models import WorkflowRecord, WorkflowState, WorkflowMode
    from datetime import datetime
    
    async def mock_start(req):
        return WorkflowRecord(
            workflow_id="test-wf-id-123",
            quiz_url="https://example.com/quiz?attempt=1&cmid=2",
            mode=WorkflowMode.PRACTICE,
            state=WorkflowState.PENDING,
            auto_submit=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    monkeypatch.setattr("app.routes.workflows.workflow_service.start_workflow", mock_start)
    
    res = client.post("/api/workflows", json={
        "quiz_url": "https://elearn.example.edu/moodle/mod/quiz/attempt.php?attempt=123&cmid=456",
        "mode": "practice",
        "auto_submit": False,
    })
    assert res.status_code == 201
    data = res.json()
    assert data["success"] is True
    assert data["workflow_id"] == "test-wf-id-123"


def test_get_nonexistent_workflow(client):
    res = client.get("/api/workflows/nonexistent-id")
    assert res.status_code == 404


def test_notifications_endpoint(client):
    res = client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()
    assert "notifications" in data
    assert isinstance(data["notifications"], list)


def test_dashboard_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "Quiz" in res.text or "quiz" in res.text.lower()


def test_settings_page(client):
    res = client.get("/settings")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_workflow_detail_not_found(client):
    res = client.get("/workflow/nonexistent-123")
    assert res.status_code == 404


def test_workflow_mode_validation(client):
    """Invalid mode should be rejected."""
    res = client.post("/api/workflows", json={
        "quiz_url": "https://example.com/quiz?attempt=1",
        "mode": "invalid_mode",
    })
    assert res.status_code == 422
