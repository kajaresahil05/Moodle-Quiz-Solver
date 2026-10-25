"""
tests/test_database.py
Tests for database CRUD operations.
"""
import pytest
from datetime import datetime

from app import database as db
from app.models import WorkflowState, WorkflowUpdate, WorkflowMode


def test_create_and_get_workflow():
    record = db.create_workflow(
        quiz_url="https://elearn.example.edu/moodle/mod/quiz/attempt.php?attempt=123&cmid=456",
        mode="practice",
        auto_submit=False,
    )
    assert record.workflow_id is not None
    assert record.state == WorkflowState.PENDING
    assert record.mode == WorkflowMode.PRACTICE
    assert record.submitted is False

    fetched = db.get_workflow(record.workflow_id)
    assert fetched is not None
    assert fetched.workflow_id == record.workflow_id


def test_url_sanitization():
    """Session tokens must not be stored."""
    dirty_url = "https://elearn.example.edu/moodle/mod/quiz/attempt.php?attempt=99&cmid=55&sesskey=SECRET123&token=ABCD"
    record = db.create_workflow(quiz_url=dirty_url, mode="practice")
    # sesskey and token should not be in stored URL
    assert "sesskey" not in record.quiz_url
    assert "SECRET123" not in record.quiz_url
    assert "ABCD" not in record.quiz_url
    # Safe params should be present
    assert "attempt=99" in record.quiz_url
    assert "cmid=55" in record.quiz_url


def test_list_workflows():
    db.create_workflow("https://example.com/quiz?attempt=1&cmid=1", "practice")
    db.create_workflow("https://example.com/quiz?attempt=2&cmid=2", "review")
    workflows = db.list_workflows(limit=10)
    assert len(workflows) >= 2


def test_update_workflow_state():
    record = db.create_workflow("https://example.com/quiz?attempt=1", "practice")
    updated = db.update_workflow(
        record.workflow_id,
        WorkflowUpdate(state=WorkflowState.RUNNING, answered_questions=5, total_questions=10)
    )
    assert updated.state == WorkflowState.RUNNING
    assert updated.answered_questions == 5
    assert updated.total_questions == 10


def test_delete_workflow():
    record = db.create_workflow("https://example.com/quiz?attempt=1", "practice")
    wid = record.workflow_id
    deleted = db.delete_workflow(wid)
    assert deleted is True
    assert db.get_workflow(wid) is None


def test_log_and_list_events():
    record = db.create_workflow("https://example.com/quiz?attempt=1", "practice")
    db.log_event(record.workflow_id, "test_event", "Test message")
    db.log_event(record.workflow_id, "another_event", "Another message")
    events = db.list_events(record.workflow_id)
    assert len(events) >= 2
    assert any(e.event_type == "test_event" for e in events)


def test_save_question_record():
    record = db.create_workflow("https://example.com/quiz?attempt=1", "practice")
    q_rec = db.save_question_record(
        workflow_id=record.workflow_id,
        question_id="q_1",
        page=0,
        question_text="What is a Boolean query?",
        question_type="single",
        options=[{"id": "a", "text": "AND query"}, {"id": "b", "text": "keyword"}],
        ai_suggestion=["a"],
        explanation="AND is Boolean",
        confidence=0.9,
        is_ambiguous=False,
        answered=True,
    )
    assert q_rec.question_id == "q_1"
    assert q_rec.answered is True
    
    records = db.list_question_records(record.workflow_id)
    assert len(records) == 1


def test_workflow_not_found():
    assert db.get_workflow("nonexistent-id-12345") is None


def test_update_nonexistent_workflow_returns_none():
    result = db.update_workflow("ghost-id", WorkflowUpdate(state=WorkflowState.FAILED))
    assert result is None


def test_update_question_record_answered():
    wf = db.create_workflow(
        quiz_url="https://moodle.example.com/mod/quiz/attempt.php?attempt=777&cmid=1",
        mode="practice",
        auto_submit=False,
    )
    db.save_question_record(
        workflow_id=wf.workflow_id,
        question_id="q_check",
        page=0,
        question_text="Sample question",
        question_type="single_choice",
        options=[],
        ai_suggestion=["1"],
        explanation="test",
        confidence=0.95,
        is_ambiguous=False,
        answered=False,
    )

    records = db.list_question_records(wf.workflow_id)
    assert records[0].answered is False

    db.update_question_record_answered(wf.workflow_id, "q_check", True)
    updated_records = db.list_question_records(wf.workflow_id)
    assert updated_records[0].answered is True


def test_user_workflow_isolation():
    wf_user1 = db.create_workflow(
        "https://example.com/quiz?attempt=10",
        "practice",
        user_id="user_alpha",
    )
    wf_user2 = db.create_workflow(
        "https://example.com/quiz?attempt=20",
        "practice",
        user_id="user_beta",
    )

    user1_wfs = db.list_workflows(user_id="user_alpha")
    user2_wfs = db.list_workflows(user_id="user_beta")

    assert any(w.workflow_id == wf_user1.workflow_id for w in user1_wfs)
    assert not any(w.workflow_id == wf_user2.workflow_id for w in user1_wfs)

    assert any(w.workflow_id == wf_user2.workflow_id for w in user2_wfs)
    assert not any(w.workflow_id == wf_user1.workflow_id for w in user2_wfs)

