"""
tests/test_auth.py
Unit and integration tests for Moodle ID and password authentication flow.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth_service


@pytest.fixture
def unauth_client():
    """Client with no session / cookies."""
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def redirect_client():
    """Client that follows redirects."""
    with TestClient(app, follow_redirects=True) as c:
        yield c


def test_dashboard_redirects_to_login_when_unauthenticated(unauth_client):
    """Visiting / without session must redirect to /login."""
    res = unauth_client.get("/")
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_settings_redirects_to_login_when_unauthenticated(unauth_client):
    """Visiting /settings without session must redirect to /login?next=/settings."""
    res = unauth_client.get("/settings")
    assert res.status_code == 303
    assert "/login" in res.headers["location"]


def test_login_page_renders_fields(redirect_client):
    """Login page must render Moodle ID and Password inputs."""
    res = redirect_client.get("/login")
    assert res.status_code == 200
    assert "Moodle ID" in res.text
    assert "name=\"moodle_id\"" in res.text
    assert "name=\"password\"" in res.text
    assert "Sign In" in res.text


def test_login_missing_fields_returns_error(unauth_client):
    """Submitting empty credentials must show validation error."""
    res = unauth_client.post("/login", data={"moodle_id": "", "password": ""})
    assert res.status_code == 400
    assert "Please enter both your Moodle ID and Password" in res.text


def test_login_success_sets_cookie_and_redirects(unauth_client):
    """Submitting valid credentials creates a session cookie and redirects to dashboard."""
    res = unauth_client.post(
        "/login",
        data={"moodle_id": "23104059", "password": "SecretPassword123", "remember": "true"},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/"
    assert auth_service.COOKIE_NAME in res.cookies

    cookie_val = res.cookies[auth_service.COOKIE_NAME]
    assert len(cookie_val) > 20

    # Verify session exists in DB
    session = auth_service.db.get_session(cookie_val)
    assert session is not None
    assert session["moodle_id"] == "23104059"
    assert session["moodle_password"] == "SecretPassword123"


def test_dashboard_accessible_after_login(unauth_client):
    """After login, the user can access the dashboard and their Moodle ID is displayed."""
    login_res = unauth_client.post(
        "/login",
        data={"moodle_id": "student_jane", "password": "JanePassword"},
    )
    assert login_res.status_code == 303
    cookie = login_res.cookies[auth_service.COOKIE_NAME]

    # Visit dashboard with session cookie
    dash_res = unauth_client.get("/", cookies={auth_service.COOKIE_NAME: cookie})
    assert dash_res.status_code == 200
    assert "student_jane" in dash_res.text
    assert "Quiz Automation Dashboard" in dash_res.text
    assert "Sign Out" in dash_res.text or "Logout" in dash_res.text


def test_login_page_redirects_if_already_logged_in(unauth_client):
    """If already authenticated, visiting /login redirects back to /."""
    token = auth_service.create_user_session("active_user", "password123")
    res = unauth_client.get("/login", cookies={auth_service.COOKIE_NAME: token})
    assert res.status_code == 303
    assert res.headers["location"] == "/"


def test_logout_clears_session_and_cookie(unauth_client):
    """Logging out terminates the session in DB and deletes the cookie."""
    token = auth_service.create_user_session("logout_user", "mypass")
    res = unauth_client.get("/logout", cookies={auth_service.COOKIE_NAME: token})
    assert res.status_code == 303
    assert "/login?logged_out=1" in res.headers["location"]

    # Verify session is deleted
    assert auth_service.db.get_session(token) is None


def test_api_auth_login_and_me(unauth_client):
    """JSON API login sets cookie and /api/auth/me returns authenticated status."""
    res = unauth_client.post(
        "/api/auth/login",
        json={"moodle_id": "api_user_88", "password": "api_password_88"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["moodle_id"] == "api_user_88"
    assert "token" in data

    token = data["token"]

    # Call /api/auth/me
    me_res = unauth_client.get("/api/auth/me", cookies={auth_service.COOKIE_NAME: token})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["authenticated"] is True
    assert me_data["moodle_id"] == "api_user_88"


def test_api_auth_logout(unauth_client):
    """API logout terminates session."""
    token = auth_service.create_user_session("api_logout_user", "password")
    res = unauth_client.post("/api/auth/logout", cookies={auth_service.COOKIE_NAME: token})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert auth_service.db.get_session(token) is None
