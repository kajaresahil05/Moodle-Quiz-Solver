"""
app/schemas.py
Additional Pydantic schemas for API request/response validation.
Re-exports from models for backward compatibility.
"""
from app.models import (
    GeminiAnswer,
    QuizOption,
    QuizQuestion,
    QuestionType,
    WorkflowCreate,
    WorkflowMode,
    WorkflowRecord,
    WorkflowResponse,
    WorkflowState,
    WorkflowUpdate,
    StatusResponse,
    QuestionRecord,
    EventRecord,
)

__all__ = [
    "GeminiAnswer",
    "QuizOption",
    "QuizQuestion",
    "QuestionType",
    "WorkflowCreate",
    "WorkflowMode",
    "WorkflowRecord",
    "WorkflowResponse",
    "WorkflowState",
    "WorkflowUpdate",
    "StatusResponse",
    "QuestionRecord",
    "EventRecord",
]
