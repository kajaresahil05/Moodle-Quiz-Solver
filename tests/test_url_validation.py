"""
tests/test_url_validation.py
Tests for URL validation and SSRF protection.
"""
import pytest
from app.services.browser_service import validate_quiz_url


@pytest.mark.asyncio
async def test_valid_moodle_url():
    ok, err = await validate_quiz_url(
        "https://elearn.example.edu/moodle/mod/quiz/attempt.php?attempt=1234&cmid=5678"
    )
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_missing_scheme_rejected():
    ok, err = await validate_quiz_url("elearn.example.edu/moodle/quiz")
    assert ok is False
    assert "http" in err.lower() or "url" in err.lower()


@pytest.mark.asyncio
async def test_loopback_ip():
    # Localhost is allowed for dev
    ok, err = await validate_quiz_url("http://localhost:8080/quiz")
    assert ok is True


@pytest.mark.asyncio
async def test_ftp_scheme_rejected():
    ok, err = await validate_quiz_url("ftp://files.example.com/quiz")
    assert ok is False


@pytest.mark.asyncio
async def test_empty_url_rejected():
    ok, err = await validate_quiz_url("")
    assert ok is False


@pytest.mark.asyncio
async def test_valid_https():
    ok, err = await validate_quiz_url("https://moodle.college.edu/mod/quiz/attempt.php?attempt=99")
    assert ok is True


@pytest.mark.asyncio
async def test_view_url_accepted():
    ok, err = await validate_quiz_url("https://elearn.apsit.edu.in/moodle/mod/quiz/view.php?id=78208")
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_quoted_and_whitespace_url_accepted():
    ok, err = await validate_quiz_url('  "https://moodle.college.edu/mod/quiz/view.php?id=123"  ')
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_startattempt_url_accepted():
    ok, err = await validate_quiz_url("https://elearn.apsit.edu.in/moodle/mod/quiz/startattempt.php?cmid=78208")
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_summary_url_accepted():
    ok, err = await validate_quiz_url("https://elearn.apsit.edu.in/moodle/mod/quiz/summary.php?attempt=185199&cmid=78208")
    assert ok is True
    assert err == ""

