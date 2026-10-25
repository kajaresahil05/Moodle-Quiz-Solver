"""
app/routes/workflows.py
REST API routes for workflow management.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app import database as db
from app.models import (
    StatusResponse,
    WorkflowCreate,
    WorkflowMode,
    WorkflowRecord,
    WorkflowResponse,
    WorkflowState,
    WorkflowUpdate,
)
from app.services import auth_service, workflow_service

logger = logging.getLogger(__name__)


def _format_iso(dt) -> str:
    """Format datetime as UTC ISO string with explicit timezone suffix."""
    if not dt:
        return ""
    if dt.tzinfo:
        return dt.isoformat()
    return f"{dt.isoformat()}Z"
router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(request: WorkflowCreate, http_req: Request):
    """
    Start a new quiz automation workflow.
    
    - **quiz_url**: Full URL to the Moodle quiz attempt page
    - **mode**: 'practice' (click answers) or 'review' (suggestions only)
    - **auto_submit**: If true and mode=practice, auto-submit after all questions
    """
    try:
        user = auth_service.get_current_user(http_req)
        moodle_username = user.get("moodle_id", "") if user else ""
        moodle_password = user.get("moodle_password", "") if user else ""

        try:
            record = await workflow_service.start_workflow(
                request,
                moodle_username=moodle_username,
                moodle_password=moodle_password,
            )
        except TypeError:
            record = await workflow_service.start_workflow(request)
        return WorkflowResponse(
            success=True,
            workflow_id=record.workflow_id,
            message=f"Workflow started in {request.mode.value} mode",
            data={"state": record.state.value},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error creating workflow: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {str(e)}")


@router.get("", response_model=List[WorkflowRecord])
async def list_workflows(limit: int = 20):
    """List all workflows, most recent first."""
    return db.list_workflows(limit=min(limit, 100))


@router.get("/{workflow_id}", response_model=WorkflowRecord)
async def get_workflow(workflow_id: str):
    """Get details of a specific workflow."""
    record = db.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return record


@router.get("/{workflow_id}/status", response_model=StatusResponse)
async def get_workflow_status(workflow_id: str):
    """Get the current status of a workflow including events."""
    record = db.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    events = db.list_events(workflow_id, limit=20)
    questions = db.list_question_records(workflow_id)
    is_running = workflow_service.is_workflow_running(workflow_id)
    
    return StatusResponse(
        workflow_id=workflow_id,
        state=record.state if not is_running else WorkflowState.RUNNING,
        mode=record.mode,
        total_questions=record.total_questions,
        answered_questions=record.answered_questions,
        submitted=record.submitted,
        error_message=record.error_message,
        events=[
            {
                "event_type": e.event_type,
                "message": e.message,
                "timestamp": _format_iso(e.created_at),
            }
            for e in events
        ],
        questions=[
            {
                "question_id": q.question_id,
                "page": q.page,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "suggested_text": q.suggested_text,
                "explanation": q.explanation,
                "confidence": q.confidence,
                "is_ambiguous": q.is_ambiguous,
                "answered": q.answered,
                "ai_provider": q.ai_provider or "Gemini",
            }
            for q in questions
        ],
    )


@router.post("/{workflow_id}/stop", response_model=WorkflowResponse)
async def stop_workflow(workflow_id: str):
    """Stop a running workflow."""
    record = db.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    stopped = await workflow_service.stop_workflow(workflow_id)
    if stopped:
        return WorkflowResponse(
            success=True,
            workflow_id=workflow_id,
            message="Workflow stopped",
        )
    return WorkflowResponse(
        success=False,
        workflow_id=workflow_id,
        message="Workflow was not running or already stopped",
    )


@router.delete("/{workflow_id}", response_model=WorkflowResponse)
async def delete_workflow(workflow_id: str):
    """Delete a workflow and all associated records."""
    # Stop if running
    await workflow_service.stop_workflow(workflow_id)
    deleted = db.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowResponse(
        success=True,
        workflow_id=workflow_id,
        message="Workflow deleted",
    )


@router.get("/{workflow_id}/questions")
async def get_workflow_questions(workflow_id: str):
    """Get all question records for a workflow."""
    record = db.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow not found")
    questions = db.list_question_records(workflow_id)
    return {"workflow_id": workflow_id, "questions": [q.model_dump() for q in questions]}


@router.get("/{workflow_id}/events")
async def get_workflow_events(workflow_id: str, limit: int = 50):
    """Get event log for a workflow."""
    record = db.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow not found")
    events = db.list_events(workflow_id, limit=min(limit, 200))
    return {
        "workflow_id": workflow_id,
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "message": e.message,
                "timestamp": _format_iso(e.created_at),
            }
            for e in events
        ],
    }
