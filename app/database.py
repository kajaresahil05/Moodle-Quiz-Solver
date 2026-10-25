"""
app/database.py
SQLite database layer with async-friendly wrapper using standard sqlite3.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from app.config import get_settings
from app.models import (
    EventRecord,
    QuestionRecord,
    WorkflowRecord,
    WorkflowState,
    WorkflowUpdate,
)

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    return get_settings().database_path


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections."""
    conn = sqlite3.connect(_get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database schema."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id     TEXT PRIMARY KEY,
                quiz_url        TEXT NOT NULL,
                mode            TEXT NOT NULL,
                state           TEXT NOT NULL DEFAULT 'pending',
                auto_submit     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                error_message   TEXT,
                total_questions INTEGER NOT NULL DEFAULT 0,
                answered_questions INTEGER NOT NULL DEFAULT 0,
                submitted       INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS question_records (
                record_id       TEXT PRIMARY KEY,
                workflow_id     TEXT NOT NULL REFERENCES workflows(workflow_id),
                question_id     TEXT NOT NULL,
                page            INTEGER NOT NULL DEFAULT 0,
                question_text   TEXT NOT NULL,
                question_type   TEXT NOT NULL,
                options_json    TEXT NOT NULL DEFAULT '[]',
                ai_suggestion   TEXT NOT NULL DEFAULT '[]',
                explanation     TEXT NOT NULL DEFAULT '',
                confidence      REAL NOT NULL DEFAULT 0.0,
                is_ambiguous    INTEGER NOT NULL DEFAULT 0,
                answered        INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                ai_provider     TEXT DEFAULT 'Gemini'
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id    TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id),
                event_type  TEXT NOT NULL,
                message     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                session_token   TEXT PRIMARY KEY,
                moodle_id       TEXT NOT NULL,
                moodle_password TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                last_active     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_workflows_state
                ON workflows(state);
            CREATE INDEX IF NOT EXISTS idx_question_records_workflow
                ON question_records(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_events_workflow
                ON events(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_moodle_id
                ON user_sessions(moodle_id);
        """)

        # Migration: ensure ai_provider column exists
        try:
            conn.execute("ALTER TABLE question_records ADD COLUMN ai_provider TEXT DEFAULT 'Gemini';")
        except sqlite3.OperationalError:
            pass  # Already exists
    logger.info("Database initialized at %s", _get_db_path())


# ─── Workflow CRUD ───────────────────────────────────────────────────────────

def create_workflow(
    quiz_url: str,
    mode: str,
    auto_submit: bool = False,
) -> WorkflowRecord:
    now = datetime.utcnow().isoformat()
    wid = str(uuid.uuid4())
    # Sanitize URL: strip query params that may contain session data
    sanitized_url = _sanitize_url(quiz_url)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO workflows
                (workflow_id, quiz_url, mode, state, auto_submit, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (wid, sanitized_url, mode, int(auto_submit), now, now),
        )

    return get_workflow(wid)  # type: ignore[return-value]


def get_workflow(workflow_id: str) -> Optional[WorkflowRecord]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_workflow(row)


def list_workflows(limit: int = 50) -> List[WorkflowRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM workflows ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_workflow(r) for r in rows]


def update_workflow(workflow_id: str, update: WorkflowUpdate) -> Optional[WorkflowRecord]:
    fields: list[str] = []
    params: list = []

    if update.state is not None:
        fields.append("state = ?")
        params.append(update.state.value)
    if update.error_message is not None:
        fields.append("error_message = ?")
        params.append(update.error_message if update.error_message != "" else None)
    if update.total_questions is not None:
        fields.append("total_questions = ?")
        params.append(update.total_questions)
    if update.answered_questions is not None:
        fields.append("answered_questions = ?")
        params.append(update.answered_questions)
    if update.submitted is not None:
        fields.append("submitted = ?")
        params.append(int(update.submitted))

    if not fields:
        return get_workflow(workflow_id)

    fields.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(workflow_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE workflows SET {', '.join(fields)} WHERE workflow_id = ?",
            params,
        )
    return get_workflow(workflow_id)


def delete_workflow(workflow_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("DELETE FROM events WHERE workflow_id = ?", (workflow_id,))
        conn.execute(
            "DELETE FROM question_records WHERE workflow_id = ?", (workflow_id,)
        )
        result = conn.execute(
            "DELETE FROM workflows WHERE workflow_id = ?", (workflow_id,)
        )
        return result.rowcount > 0


# ─── Question Records ─────────────────────────────────────────────────────────

def save_question_record(
    workflow_id: str,
    question_id: str,
    page: int,
    question_text: str,
    question_type: str,
    options: list,
    ai_suggestion: list,
    explanation: str,
    confidence: float,
    is_ambiguous: bool,
    answered: bool,
    ai_provider: str = "Gemini",
) -> QuestionRecord:
    now = datetime.utcnow().isoformat()
    rid = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO question_records
                (record_id, workflow_id, question_id, page, question_text,
                 question_type, options_json, ai_suggestion, explanation,
                 confidence, is_ambiguous, answered, created_at, ai_provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid, workflow_id, question_id, page, question_text,
                question_type, json.dumps(options), json.dumps(ai_suggestion),
                explanation, confidence, int(is_ambiguous), int(answered), now,
                ai_provider,
            ),
        )
    return _get_question_record(rid)  # type: ignore[return-value]


def _get_question_record(record_id: str) -> Optional[QuestionRecord]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM question_records WHERE record_id = ?", (record_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_question_record(row)


def list_question_records(workflow_id: str) -> List[QuestionRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM question_records WHERE workflow_id = ? ORDER BY page, question_id",
            (workflow_id,),
        ).fetchall()
    return [_row_to_question_record(r) for r in rows]


def update_question_record_answered(
    workflow_id: str,
    question_id: str,
    answered: bool,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE question_records
            SET answered = ?
            WHERE workflow_id = ? AND question_id = ?
            """,
            (int(answered), workflow_id, question_id),
        )



# ─── Events ──────────────────────────────────────────────────────────────────

def log_event(
    workflow_id: str,
    event_type: str,
    message: str,
) -> EventRecord:
    now = datetime.utcnow().isoformat()
    eid = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events (event_id, workflow_id, event_type, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (eid, workflow_id, event_type, message, now),
        )
    return EventRecord(
        event_id=eid,
        workflow_id=workflow_id,
        event_type=event_type,
        message=message,
        created_at=datetime.fromisoformat(now),
    )


def list_events(workflow_id: str, limit: int = 100) -> List[EventRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE workflow_id = ? ORDER BY created_at DESC LIMIT ?",
            (workflow_id, limit),
        ).fetchall()
    return [
        EventRecord(
            event_id=r["event_id"],
            workflow_id=r["workflow_id"],
            event_type=r["event_type"],
            message=r["message"],
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in rows
    ]


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _sanitize_url(url: str) -> str:
    """Remove query parameters that may contain session data. Keep base path."""
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    parsed = urlparse(url.strip().strip('"').strip("'"))
    # Keep only safe query params (attempt, cmid, page, id, q, forceview, showall) — drop sesskey, token etc.
    safe_keys = {"attempt", "cmid", "page", "id", "q", "forceview", "showall"}
    qs = parse_qs(parsed.query, keep_blank_values=False)
    safe_qs = {k: v for k, v in qs.items() if k in safe_keys}
    sanitized = parsed._replace(query=urlencode(safe_qs, doseq=True), fragment="")
    return urlunparse(sanitized)


def _row_to_workflow(row: sqlite3.Row) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=row["workflow_id"],
        quiz_url=row["quiz_url"],
        mode=row["mode"],
        state=row["state"],
        auto_submit=bool(row["auto_submit"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        error_message=row["error_message"],
        total_questions=row["total_questions"],
        answered_questions=row["answered_questions"],
        submitted=bool(row["submitted"]),
    )


def _row_to_question_record(row: sqlite3.Row) -> QuestionRecord:
    keys = row.keys()
    return QuestionRecord(
        record_id=row["record_id"],
        workflow_id=row["workflow_id"],
        question_id=row["question_id"],
        page=row["page"],
        question_text=row["question_text"],
        question_type=row["question_type"],
        options_json=row["options_json"],
        ai_suggestion=row["ai_suggestion"],
        explanation=row["explanation"],
        confidence=row["confidence"],
        is_ambiguous=bool(row["is_ambiguous"]),
        answered=bool(row["answered"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        ai_provider=row["ai_provider"] if ("ai_provider" in keys and row["ai_provider"]) else "Gemini",
    )


# ─── User Session Management ────────────────────────────────────────────────

def save_session(session_token: str, moodle_id: str, moodle_password: str) -> None:
    """Save or update an active user session."""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (session_token, moodle_id, moodle_password, created_at, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_token) DO UPDATE SET
                moodle_id = excluded.moodle_id,
                moodle_password = excluded.moodle_password,
                last_active = excluded.last_active;
            """,
            (session_token, moodle_id, moodle_password, now, now),
        )


def get_session(session_token: str) -> Optional[dict]:
    """Retrieve an active session by token."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT session_token, moodle_id, moodle_password, created_at, last_active
            FROM user_sessions
            WHERE session_token = ?;
            """,
            (session_token,),
        )
        row = cur.fetchone()
        if not row:
            return None

        # Update last_active
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE user_sessions SET last_active = ? WHERE session_token = ?;",
            (now, session_token),
        )
        return {
            "session_token": row["session_token"],
            "moodle_id": row["moodle_id"],
            "moodle_password": row["moodle_password"],
            "created_at": row["created_at"],
            "last_active": row["last_active"],
        }


def delete_session(session_token: str) -> bool:
    """Delete a session by token."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM user_sessions WHERE session_token = ?;",
            (session_token,),
        )
        return cur.rowcount > 0


def delete_all_sessions() -> int:
    """Delete all sessions (e.g. for testing/reset)."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM user_sessions;")
        return cur.rowcount

