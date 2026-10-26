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


def test_user_isolation_api(client):
    """Ensure user only sees their own workflows and cannot access others."""
    from app import database as db
    
    # Workflow created by other_user
    wf_other = db.create_workflow(
        "https://example.com/quiz?attempt=999",
        "practice",
        user_id="other_student",
    )
    # Workflow created by current user test_student
    wf_mine = db.create_workflow(
        "https://example.com/quiz?attempt=888",
        "practice",
        user_id="test_student",
    )

    # 1. Listing workflows should only include test_student's workflows
    res = client.get("/api/workflows")
    assert res.status_code == 200
    ids = [w["workflow_id"] for w in res.json()]
    assert wf_mine.workflow_id in ids
    assert wf_other.workflow_id not in ids

    # 2. Accessing other user's workflow should return 404
    res_other = client.get(f"/api/workflows/{wf_other.workflow_id}")
    assert res_other.status_code == 404

    # 3. Accessing own workflow should return 200
    res_mine = client.get(f"/api/workflows/{wf_mine.workflow_id}")
    assert res_mine.status_code == 200

    # 4. Detail page for other user's workflow should return 404
    page_other = client.get(f"/workflow/{wf_other.workflow_id}")
    assert page_other.status_code == 404

    # 5. Detail page for own workflow should return 200
    page_mine = client.get(f"/workflow/{wf_mine.workflow_id}")
    assert page_mine.status_code == 200


def test_pwa_manifest(client):
    res = client.get("/manifest.json")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Moodle Quiz Assistant"
    assert data["display"] == "standalone"
    assert len(data["icons"]) >= 2


def test_pwa_service_worker(client):
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers["content-type"]
    assert res.headers.get("service-worker-allowed") == "/"


def test_pwa_offline_page(client):
    res = client.get("/offline")
    assert res.status_code == 200
    assert "You're Offline" in res.text


def test_favicon(client):
    res = client.get("/favicon.ico")
    assert res.status_code == 200
    assert "image/x-icon" in res.headers["content-type"]


