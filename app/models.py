"""
app/models.py
Pydantic schemas and SQLite ORM-like data models.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ─── Enums ───────────────────────────────────────────────────────────────────

class WorkflowMode(str, enum.Enum):
    PRACTICE = "practice"
    REVIEW = "review"


class WorkflowState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class QuestionType(str, enum.Enum):
    SINGLE = "single"
    MULTI = "multi"
    UNKNOWN = "unknown"


# ─── Gemini Answer Schema ────────────────────────────────────────────────────

class GeminiAnswer(BaseModel):
    """Structured response from Gemini for a quiz question."""
    selected_option_ids: List[str] = Field(
        default_factory=list,
        description="List of option IDs to select (e.g. ['a', 'b'] or ['c'])"
    )
    explanation: str = Field(default="", description="Brief reasoning for the answer")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0 and 1"
    )
    is_ambiguous: bool = Field(
        default=False,
        description="True if the question cannot be answered reliably"
    )
    requires_image: bool = Field(
        default=False,
        description="True if the question requires visual information not provided"
    )
    ai_provider: Optional[str] = Field(
        default="Gemini",
        description="AI provider and model that answered the question"
    )


# ─── Question ────────────────────────────────────────────────────────────────

class QuizOption(BaseModel):
    option_id: str
    label: str
    text: str


class QuizQuestion(BaseModel):
    question_id: str
    page: int
    question_text: str
    question_type: QuestionType = QuestionType.UNKNOWN
    options: List[QuizOption] = Field(default_factory=list)
    current_selection: List[str] = Field(default_factory=list)


# ─── Workflow ────────────────────────────────────────────────────────────────

class WorkflowCreate(BaseModel):
    quiz_url: str
    mode: WorkflowMode = WorkflowMode.PRACTICE
    auto_submit: bool = False

    @field_validator("quiz_url")
    @classmethod
    def validate_quiz_url(cls, v: str) -> str:
        v = v.strip().strip('"').strip("'").strip()
        # Must be http/https
        if not v.startswith(("http://", "https://")):
            raise ValueError("quiz_url must start with http:// or https://")
        return v


class WorkflowRecord(BaseModel):
    workflow_id: str
    quiz_url: str  # sanitized (no session params stored)
    mode: WorkflowMode
    state: WorkflowState
    auto_submit: bool
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    total_questions: int = 0
    answered_questions: int = 0
    submitted: bool = False


class WorkflowUpdate(BaseModel):
    state: Optional[WorkflowState] = None
    error_message: Optional[str] = None
    total_questions: Optional[int] = None
    answered_questions: Optional[int] = None
    submitted: Optional[bool] = None


# ─── QuestionRecord ──────────────────────────────────────────────────────────

class QuestionRecord(BaseModel):
    record_id: str
    workflow_id: str
    question_id: str
    page: int
    question_text: str
    question_type: str
    options_json: str  # JSON string of options
    ai_suggestion: str  # JSON string of selected_option_ids
    explanation: str
    confidence: float
    is_ambiguous: bool
    answered: bool
    created_at: datetime
    ai_provider: Optional[str] = "Gemini"

    @property
    def suggested_text(self) -> str:
        """Formatted suggested answer text for display."""
        try:
            import json
            ids = json.loads(self.ai_suggestion)
            if not isinstance(ids, list):
                ids = [str(ids)]
            opts = json.loads(self.options_json)
            id_map = {str(o.get("id")): o.get("text", "") or o.get("label", "") for o in opts}
            matches = [id_map.get(str(i)) for i in ids if str(i) in id_map and id_map.get(str(i))]
            if matches:
                return ", ".join(matches)
        except Exception:
            pass
        return self.ai_suggestion


# ─── Event ───────────────────────────────────────────────────────────────────

class EventRecord(BaseModel):
    event_id: str
    workflow_id: str
    event_type: str  # e.g. "question_answered", "workflow_started", "error"
    message: str
    created_at: datetime


# ─── API Response Models ─────────────────────────────────────────────────────

class WorkflowResponse(BaseModel):
    success: bool
    workflow_id: Optional[str] = None
    message: str
    data: Optional[dict] = None


class StatusResponse(BaseModel):
    workflow_id: str
    state: WorkflowState
    mode: WorkflowMode
    total_questions: int
    answered_questions: int
    submitted: bool
    error_message: Optional[str] = None
    events: List[dict] = Field(default_factory=list)
    questions: List[dict] = Field(default_factory=list)


class QuestionSuggestion(BaseModel):
    question_id: str
    question_text: str
    suggestion: GeminiAnswer
    answered: bool
