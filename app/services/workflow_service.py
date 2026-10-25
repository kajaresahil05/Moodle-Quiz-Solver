"""
app/services/workflow_service.py
Orchestrates the full quiz automation workflow.
Modes: PRACTICE (ungraded), REVIEW (read-only with suggestions).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from app.config import get_settings
from app.models import (
    QuestionType,
    WorkflowCreate,
    WorkflowMode,
    WorkflowRecord,
    WorkflowState,
    WorkflowUpdate,
)
from app import database as db
from app.services import (
    browser_service,
    gemini_service as gem_mod,
    notification_service as notif,
)
from app.services.quiz_parser import QuizParser

logger = logging.getLogger(__name__)

# Active workflow tasks: workflow_id -> asyncio.Task
_active_tasks: Dict[str, asyncio.Task] = {}
_gemini = gem_mod.GeminiService()
_parser = QuizParser()


async def start_workflow(
    request: WorkflowCreate,
    moodle_username: str = "",
    moodle_password: str = "",
) -> WorkflowRecord:
    """
    Create a new workflow record and launch the background task.
    """
    # Validate URL
    is_valid, err = await browser_service.validate_quiz_url(request.quiz_url)
    if not is_valid:
        raise ValueError(f"Invalid quiz URL: {err}")

    # Create DB record
    record = db.create_workflow(
        quiz_url=request.quiz_url,
        mode=request.mode.value,
        auto_submit=request.auto_submit,
    )

    db.log_event(record.workflow_id, "workflow_created", f"Mode: {request.mode.value}")

    # Launch background task
    task = asyncio.create_task(
        _run_workflow(record.workflow_id, request, moodle_username, moodle_password),
        name=f"workflow_{record.workflow_id[:8]}",
    )
    _active_tasks[record.workflow_id] = task

    def _on_task_done(t: asyncio.Task) -> None:
        _active_tasks.pop(record.workflow_id, None)
        if not t.cancelled() and t.exception():
            logger.error("Workflow %s background task failed with exception: %s", record.workflow_id, t.exception(), exc_info=t.exception())

    task.add_done_callback(_on_task_done)

    logger.info("Workflow %s started (mode=%s)", record.workflow_id, request.mode.value)
    return record


async def stop_workflow(workflow_id: str) -> bool:
    """Stop a running workflow."""
    task = _active_tasks.get(workflow_id)
    if task and not task.done():
        task.cancel()
        db.update_workflow(workflow_id, WorkflowUpdate(state=WorkflowState.STOPPED))
        db.log_event(workflow_id, "workflow_stopped", "Stopped by user")
        logger.info("Workflow %s stopped", workflow_id)
        return True

    # If marked running in DB but no active task, reconcile DB state
    record = db.get_workflow(workflow_id)
    if record and record.state == WorkflowState.RUNNING:
        db.update_workflow(workflow_id, WorkflowUpdate(state=WorkflowState.STOPPED))
        db.log_event(workflow_id, "workflow_stopped", "Stopped (reconciled)")
        return True

    return False


def is_workflow_running(workflow_id: str) -> bool:
    """Check if a workflow task is currently active."""
    task = _active_tasks.get(workflow_id)
    return task is not None and not task.done()


async def _run_workflow(
    workflow_id: str,
    request: WorkflowCreate,
    moodle_username: str = "",
    moodle_password: str = "",
) -> None:
    """Main workflow execution logic."""
    try:
        db.update_workflow(workflow_id, WorkflowUpdate(state=WorkflowState.RUNNING))
        clean_url = request.quiz_url.strip().strip('"').strip("'")
        if "#" in clean_url:
            clean_url = clean_url.split("#")[0]
        # If the user copied a mid-quiz URL (e.g. &page=3), start from beginning page=0 so all questions are answered
        if "/mod/quiz/attempt.php" in clean_url and "page=" in clean_url:
            clean_url = re.sub(r'([?&])page=\d+', r'\g<1>page=0', clean_url)

        await notif.notify_workflow_started(workflow_id, clean_url)
        db.log_event(workflow_id, "workflow_started", f"Navigating to quiz URL: {clean_url}")

        # Navigate to quiz
        page = await browser_service.get_active_page()
        await browser_service.navigate_to(clean_url)
        await asyncio.sleep(2)  # Brief pause for page settle

        # Check login
        if await browser_service.check_login_required(page):
            settings = get_settings()
            active_user = moodle_username or settings.moodle_username
            active_pwd = moodle_password or settings.moodle_password
            if active_user and active_pwd:
                db.log_event(workflow_id, "info", f"Login required - attempting auto-login as {active_user}")
                logged_in = await browser_service.perform_login(active_user, active_pwd, page)
                if logged_in:
                    db.log_event(workflow_id, "info", "Auto-login succeeded")
                    page = await browser_service.get_active_page()
                    # If not on quiz page after login, navigate back to quiz URL
                    if not await browser_service.check_is_moodle_quiz(page):
                        await browser_service.navigate_to(clean_url)
                        await asyncio.sleep(2)
                        page = await browser_service.get_active_page()
                else:
                    db.update_workflow(workflow_id, WorkflowUpdate(
                        state=WorkflowState.FAILED,
                        error_message=f"Automatic login failed for {active_user} - please verify credentials"
                    ))
                    await notif.notify_login_required(workflow_id)
                    db.log_event(workflow_id, "error", f"Auto-login failed for {active_user}")
                    return
            else:
                db.update_workflow(workflow_id, WorkflowUpdate(
                    state=WorkflowState.FAILED,
                    error_message="Login required - no Moodle credentials provided"
                ))
                await notif.notify_login_required(workflow_id)
                db.log_event(workflow_id, "error", "Login required - user must log in to Moodle")
                return

        # If currently on a view page, course page, or start page, attempt to start/continue the quiz
        await browser_service.check_and_start_attempt_if_view_page(page)
        page = await browser_service.get_active_page()

        # Check for secure window launch prompt if present
        await browser_service.check_and_launch_secure_window_if_prompted(page)
        page = await browser_service.get_active_page()

        # Check it's actually an active quiz attempt or summary page (retry briefly for slow redirects)
        is_quiz = await browser_service.check_is_moodle_quiz(page)
        if not is_quiz:
            for _ in range(4):
                await asyncio.sleep(1)
                page = await browser_service.get_active_page()
                if await browser_service.check_is_moodle_quiz(page):
                    is_quiz = True
                    break

        if not is_quiz:
            try:
                body_text = await page.inner_text("body")
            except Exception:
                body_text = ""

            if "No more attempts are allowed" in body_text or "Your final grade for this quiz" in body_text:
                error_msg = "Quiz attempt already completed/finished. No active attempts remaining for this quiz."
            elif "review.php" in page.url:
                error_msg = "Quiz attempt is already completed/finished (review URL provided)."
            elif "closed on" in body_text.lower() or "quiz closed" in body_text.lower():
                error_msg = "Quiz has already closed and is no longer accepting attempts."
            elif "not be available until" in body_text.lower() or "not currently available" in body_text.lower():
                error_msg = "Quiz is not currently open for attempts (scheduled for a future time)."
            elif "password" in body_text.lower() and ("required" in body_text.lower() or "enter" in body_text.lower()):
                error_msg = "Quiz requires a password to attempt."
            elif "/mod/quiz/view.php" in page.url:
                error_msg = "Quiz has not been started yet or is not currently open for attempts."
            else:
                error_msg = f"URL redirected to {page.url[:80]} - not an active Moodle quiz attempt page"

            db.update_workflow(workflow_id, WorkflowUpdate(
                state=WorkflowState.FAILED,
                error_message=error_msg
            ))
            db.log_event(workflow_id, "error", error_msg)
            return

        total_answered = 0
        total_questions_count = 0
        page_num = 0
        max_pages = 100  # Safety limit

        # Process each page
        while page_num < max_pages:
            # Check for cancellation
            await asyncio.sleep(0)  # Yield to event loop

            page = await browser_service.get_active_page()
            current_url = page.url

            # Check if we've reached the summary page
            if "/mod/quiz/summary.php" in current_url:
                logger.info("Reached quiz summary page")
                db.log_event(workflow_id, "summary_reached", "On quiz summary page")
                break

            # Extract questions from current page
            questions = await _parser.extract_current_page_questions(page)
            if not questions:
                logger.warning("No questions found on page %d, trying to advance", page_num)
                db.log_event(workflow_id, "warning", f"No questions found on page {page_num}")
                # Try going to next page
                advanced = await browser_service.click_next_page(page)
                if not advanced:
                    break
                page_num += 1
                continue

            total_questions_count += len(questions)
            db.update_workflow(workflow_id, WorkflowUpdate(total_questions=total_questions_count))
            db.log_event(workflow_id, "page_started", f"Processing page {page_num} with {len(questions)} questions")

            # Process each question
            for question in questions:
                try:
                    answered = await _process_question(
                        workflow_id=workflow_id,
                        question=question,
                        page=page,
                        mode=request.mode,
                    )
                    if answered:
                        total_answered += 1
                        db.update_workflow(
                            workflow_id,
                            WorkflowUpdate(answered_questions=total_answered),
                        )
                    await asyncio.sleep(3.5)  # Pause to avoid rate limits and simulate natural timing
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Error processing question %s: %s", question.question_id, e)
                    db.log_event(workflow_id, "error", f"Question {question.question_id}: {str(e)[:200]}")

            # Try to go to next page
            advanced = await browser_service.click_next_page(page)
            if not advanced:
                # Try Finish attempt
                finished = await browser_service.click_finish_attempt(page)
                if not finished:
                    break
            page_num += 1
            await asyncio.sleep(1)

        # Handle summary page and auto-submit
        page = await browser_service.get_active_page()
        await _handle_completion(workflow_id, request, page, total_answered, total_questions_count)

    except asyncio.CancelledError:
        logger.info("Workflow %s was cancelled", workflow_id)
        raise
    except Exception as e:
        err_str = str(e).strip() or f"{type(e).__name__}: {repr(e)}"
        db.update_workflow(workflow_id, WorkflowUpdate(
            state=WorkflowState.FAILED,
            error_message=err_str[:500],
        ))
        await notif.notify_workflow_error(workflow_id, err_str)
        db.log_event(workflow_id, "error", f"Workflow failed: {err_str[:300]}")


async def _process_question(
    workflow_id: str,
    question,
    page,
    mode: WorkflowMode,
) -> bool:
    """
    Process a single question: get AI suggestion, optionally answer it.
    Returns True if an answer was recorded.
    """
    # Get AI suggestion
    try:
        suggestion = await _gemini.get_answer_suggestion(
            question_text=question.question_text,
            options=question.options,
            question_type=question.question_type,
        )
    except Exception as e:
        logger.error("Gemini error for question %s: %s", question.question_id, e)
        await notif.notify_api_error(workflow_id, str(e))
        suggestion = None

    # Save question record
    db.save_question_record(
        workflow_id=workflow_id,
        question_id=question.question_id,
        page=question.page,
        question_text=question.question_text[:2000],
        question_type=question.question_type.value,
        options=[{"id": o.option_id, "label": o.label, "text": o.text} for o in question.options],
        ai_suggestion=suggestion.selected_option_ids if suggestion else [],
        explanation=suggestion.explanation if suggestion else "",
        confidence=suggestion.confidence if suggestion else 0.0,
        is_ambiguous=suggestion.is_ambiguous if suggestion else True,
        answered=False,
        ai_provider=suggestion.ai_provider if suggestion and suggestion.ai_provider else "Gemini",
    )

    if not suggestion or suggestion.is_ambiguous or suggestion.requires_image:
        await notif.notify_manual_review(
            workflow_id,
            question.question_id,
            "Ambiguous or image-required question"
        )
        db.log_event(
            workflow_id, "manual_review",
            f"Question {question.question_id}: {suggestion.explanation if suggestion else 'No suggestion'}"
        )
        return False

    # In REVIEW mode, only suggest — don't click
    if mode == WorkflowMode.REVIEW:
        db.log_event(
            workflow_id, "suggestion_only",
            f"Question {question.question_id}: suggestion={suggestion.selected_option_ids}"
        )
        return True

    # In PRACTICE mode, actually click the answers
    answered = False
    if not suggestion.selected_option_ids:
        return False

    # Find the question block on the page
    try:
        q_blocks = await page.query_selector_all(".que")
        target_block = None
        for block in q_blocks:
            bid = await block.get_attribute("id")
            if bid and question.question_id in bid:
                target_block = block
                break
            # Try by question number
            no_el = await block.query_selector(".info .no")
            if no_el:
                no_text = await no_el.inner_text()
                if question.question_id.endswith(f"_{no_text.strip()}"):
                    target_block = block
                    break

        if target_block is None:
            # Fall back to first unprocessed block
            logger.warning("Could not find block for question %s, skipping", question.question_id)
            return False

        if question.question_type == QuestionType.SINGLE:
            # Radio: select first suggested option
            opt_val = suggestion.selected_option_ids[0]
            answered = await browser_service.select_radio_option(page, target_block, opt_val)
        elif question.question_type == QuestionType.MULTI:
            # Checkbox: select all suggested options
            for opt_val in suggestion.selected_option_ids:
                ok = await browser_service.select_checkbox_option(page, target_block, opt_val, True)
                if ok:
                    answered = True

        if answered:
            db.update_question_record_answered(workflow_id, question.question_id, True)
            db.log_event(
                workflow_id, "question_answered",
                f"Q{question.question_id}: selected={suggestion.selected_option_ids}"
            )


    except Exception as e:
        logger.error("Error answering question %s: %s", question.question_id, e)
        answered = False

    return answered


async def _handle_completion(
    workflow_id: str,
    request: WorkflowCreate,
    page,
    total_answered: int,
    total_questions: int,
) -> None:
    """Handle post-processing after all pages are done."""
    current_url = page.url

    if "/mod/quiz/summary.php" in current_url:
        # Parse summary
        summary = await _parser.extract_summary_page(page)
        unanswered = summary.get("has_unanswered", False)

        if unanswered:
            db.log_event(workflow_id, "warning", "Some questions are unanswered according to summary")

        # Safety Verification: NEVER auto-submit if any question had API errors or was unanswered!
        q_records = db.list_question_records(workflow_id)
        api_error_records = [
            q for q in q_records
            if "API error" in (q.explanation or "")
            or "failed" in (q.explanation or "").lower()
            or not q.ai_suggestion
        ]

        unanswered_records = [q for q in q_records if not q.answered]

        has_issues = (
            bool(api_error_records)
            or bool(unanswered_records)
            or unanswered
            or total_answered == 0
            or (total_questions > 0 and total_answered < total_questions)
        )

        if has_issues:
            issues = []
            if api_error_records:
                issues.append(f"{len(api_error_records)} question(s) had Gemini API errors")
            if unanswered_records or (total_questions > 0 and total_answered < total_questions):
                cnt = len(unanswered_records) if unanswered_records else (total_questions - total_answered)
                issues.append(f"{cnt} question(s) left unanswered")
            issue_msg = "; ".join(issues) or "Unanswered questions detected"

            logger.warning("Auto-submit PREVENTED for workflow %s: %s", workflow_id, issue_msg)
            db.log_event(workflow_id, "warning", f"AUTO-SUBMISSION BLOCKED FOR SAFETY: {issue_msg}. The quiz was NOT submitted.")
            await notif.notify_workflow_error(workflow_id, f"Auto-submit blocked: {issue_msg}. Please review and submit manually in Moodle.")

            db.update_workflow(workflow_id, WorkflowUpdate(
                state=WorkflowState.COMPLETED,
                submitted=False,
                answered_questions=total_answered,
                error_message=f"Submission blocked for safety: {issue_msg}"
            ))
            await notif.notify_workflow_completed(workflow_id, total_answered, total_questions)
            return

        # Auto-submit only if explicitly requested + practice mode AND all questions answered cleanly
        if request.auto_submit and request.mode == WorkflowMode.PRACTICE:
            db.log_event(workflow_id, "submitting", "All questions answered. Auto-submit: clicking Submit all and finish")
            submitted = await browser_service.submit_quiz_final(page)

            if submitted:
                # Wait up to 10 seconds for Moodle to process submission and redirect away from summary/attempt
                is_review = False
                for _ in range(10):
                    await asyncio.sleep(1)
                    final_url = page.url
                    if "review.php" in final_url or "view.php" in final_url or ("attempt.php" not in final_url and "summary.php" not in final_url):
                        is_review = True
                        break
                    try:
                        body_txt = await page.inner_text("body")
                        if any(phrase in body_txt for phrase in [
                            "You are not allowed to review this quiz",
                            "Finished",
                            "State: Finished",
                            "Make attempts: 1",
                            "Overall feedback",
                            "Summary of your previous attempts",
                        ]):
                            is_review = True
                            break
                    except Exception:
                        pass

                if is_review:
                    db.update_workflow(workflow_id, WorkflowUpdate(
                        state=WorkflowState.COMPLETED,
                        submitted=True,
                        answered_questions=total_answered,
                        error_message=None,
                    ))
                    await notif.notify_submission_verified(workflow_id)
                    db.log_event(workflow_id, "submitted", "Quiz submission verified by Moodle")
                else:
                    db.update_workflow(workflow_id, WorkflowUpdate(
                        state=WorkflowState.COMPLETED,
                        answered_questions=total_answered,
                        error_message="Submission status unclear - please verify manually",
                    ))
                    db.log_event(workflow_id, "warning", "Submission status unclear")
            else:
                db.update_workflow(workflow_id, WorkflowUpdate(
                    state=WorkflowState.COMPLETED,
                    answered_questions=total_answered,
                    error_message="Auto-submit failed - please submit manually",
                ))
                db.log_event(workflow_id, "warning", "Auto-submit failed")
        else:
            # Not auto-submitting — inform user
            db.update_workflow(workflow_id, WorkflowUpdate(
                state=WorkflowState.COMPLETED,
                answered_questions=total_answered,
            ))
            db.log_event(
                workflow_id, "completed",
                "Quiz processing complete. Please review and submit manually."
            )
    else:
        db.update_workflow(workflow_id, WorkflowUpdate(
            state=WorkflowState.COMPLETED,
            answered_questions=total_answered,
        ))
        db.log_event(workflow_id, "completed", "Workflow complete")

    await notif.notify_workflow_completed(workflow_id, total_answered, total_questions)
