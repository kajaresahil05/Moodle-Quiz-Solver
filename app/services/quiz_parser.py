"""
app/services/quiz_parser.py
Parses Moodle quiz HTML pages using Playwright Page objects.
Handles: single-select (radio), multi-select (checkbox), question text, options.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from app.models import QuestionType, QuizOption, QuizQuestion

logger = logging.getLogger(__name__)


class QuizParser:
    """
    Stateless parser that extracts questions and options from a live Playwright page.
    All DOM locators use accessible attributes / verified selectors.
    """

    async def extract_current_page_questions(
        self, page  # playwright.async_api.Page
    ) -> List[QuizQuestion]:
        """
        Extract all quiz questions visible on the current page.
        Handles Moodle's standard quiz page layout.
        """
        questions: List[QuizQuestion] = []

        try:
            # Wait for quiz content to load
            await page.wait_for_selector(".que", timeout=15000)
        except Exception:
            logger.warning("No question blocks (.que) found on page")
            return questions

        # Get current page number from URL or breadcrumb
        current_page = await self._get_page_number(page)

        # Find all question containers
        question_blocks = await page.query_selector_all(".que")
        logger.info("Found %d question blocks on page %d", len(question_blocks), current_page)

        for block in question_blocks:
            try:
                question = await self._parse_question_block(block, current_page)
                if question:
                    questions.append(question)
            except Exception as e:
                logger.error("Error parsing question block: %s", e)

        return questions

    async def _parse_question_block(self, block, page_num: int) -> Optional[QuizQuestion]:
        """Parse a single .que element."""
        # Get question ID from element attributes
        q_id = await self._get_question_id(block)

        # Get question text
        q_text = await self._get_question_text(block)
        if not q_text:
            return None

        # Determine question type (radio = single, checkbox = multi)
        q_type = await self._get_question_type(block)

        # Get all options
        options = await self._get_options(block, q_type)

        # Get currently selected options
        current_selection = await self._get_current_selection(block, q_type)

        return QuizQuestion(
            question_id=q_id,
            page=page_num,
            question_text=q_text,
            question_type=q_type,
            options=options,
            current_selection=current_selection,
        )

    async def _get_question_id(self, block) -> str:
        """Extract question identifier."""
        try:
            q_id = await block.get_attribute("id")
            if q_id:
                # e.g. "q2" or "question-1234-2" → normalize
                return re.sub(r"[^a-zA-Z0-9_-]", "_", q_id)
        except Exception:
            pass

        try:
            # Try .info > .no span
            no_el = await block.query_selector(".info .no")
            if no_el:
                text = (await no_el.inner_text()).strip()
                return f"q_{text}"
        except Exception:
            pass

        return f"q_unknown_{id(block)}"

    async def _get_question_text(self, block) -> str:
        """Extract question text."""
        selectors = [
            ".qtext",
            ".content .formulation .qtext",
            ".formulation p",
            ".qtext p",
        ]
        for sel in selectors:
            try:
                el = await block.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    async def _get_question_type(self, block) -> QuestionType:
        """Determine if question is single or multi select."""
        try:
            # Radio buttons = single select
            radio = await block.query_selector('input[type="radio"]')
            if radio:
                return QuestionType.SINGLE

            # Checkboxes = multi select
            checkbox = await block.query_selector('input[type="checkbox"]')
            if checkbox:
                return QuestionType.MULTI
        except Exception:
            pass
        return QuestionType.UNKNOWN

    async def _get_options(self, block, q_type: QuestionType) -> List[QuizOption]:
        """Extract all answer options."""
        options: List[QuizOption] = []

        input_type = "radio" if q_type == QuestionType.SINGLE else "checkbox"
        try:
            inputs = await block.query_selector_all(f'input[type="{input_type}"]')
        except Exception:
            return options

        for inp in inputs:
            try:
                option_id = await inp.get_attribute("value") or ""
                input_id = await inp.get_attribute("id") or ""
                aria_lbl = await inp.get_attribute("aria-labelledby") or ""

                label_text = ""

                # 1. Try aria-labelledby (standard in Moodle 4.x)
                if aria_lbl:
                    try:
                        lbl_el = await block.query_selector(f'[id="{aria_lbl}"]')
                        if lbl_el:
                            label_text = (await lbl_el.inner_text()).strip()
                    except Exception:
                        pass

                # 2. Try standard label[for="..."]
                if not label_text and input_id:
                    try:
                        lbl_el = await block.query_selector(f'label[for="{input_id}"]')
                        if lbl_el:
                            label_text = (await lbl_el.inner_text()).strip()
                    except Exception:
                        pass

                # 3. Try parent container answer-label or .flex-fill
                if not label_text:
                    try:
                        label_text = await inp.evaluate(
                            """el => {
                                const parent = el.closest('.r0, .r1, div');
                                if (parent) {
                                    const al = parent.querySelector('[data-region="answer-label"], .answernumber, .flex-fill, label');
                                    if (al) return al.innerText.trim();
                                    return parent.innerText.trim();
                                }
                                return '';
                            }"""
                        )
                    except Exception:
                        pass

                # Clean up multiple whitespaces/newlines (e.g. 'a.\n0.7' -> 'a. 0.7')
                if label_text:
                    label_text = " ".join(label_text.split())

                # Determine letter label (a, b, c, d)
                label_letter = chr(ord('a') + len(options)) if len(options) < 26 else str(len(options))

                options.append(QuizOption(
                    option_id=option_id or label_letter,
                    label=label_letter,
                    text=label_text or f"Option {label_letter}",
                ))
            except Exception as e:
                logger.debug("Error parsing option: %s", e)

        return options

    async def _get_current_selection(self, block, q_type: QuestionType) -> List[str]:
        """Get currently selected option IDs."""
        selected: List[str] = []
        input_type = "radio" if q_type == QuestionType.SINGLE else "checkbox"
        try:
            inputs = await block.query_selector_all(f'input[type="{input_type}"]')
            for inp in inputs:
                if await inp.is_checked():
                    val = await inp.get_attribute("value") or ""
                    if val:
                        selected.append(val)
        except Exception as e:
            logger.debug("Error getting current selection: %s", e)
        return selected

    async def _get_page_number(self, page) -> int:
        """Extract current page number from URL."""
        try:
            url = page.url
            match = re.search(r"[?&]page=(\d+)", url)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return 0

    async def extract_summary_page(self, page) -> dict:
        """
        Parse the quiz summary page.
        Returns: {
            "question_statuses": [{"number": int, "status": str}],
            "has_unanswered": bool,
            "can_submit": bool,
        }
        """
        result = {
            "question_statuses": [],
            "has_unanswered": False,
            "can_submit": False,
        }

        try:
            # Wait for summary table
            await page.wait_for_selector(".mod-quiz-attemptsum", timeout=10000)
        except Exception:
            try:
                await page.wait_for_selector("table.quizsummary", timeout=5000)
            except Exception:
                logger.warning("Summary page structure not found")
                return result

        try:
            # Find all question rows
            rows = await page.query_selector_all(".mod-quiz-attemptsum tbody tr, table.quizsummary tbody tr")
            for row in rows:
                try:
                    cells = await row.query_selector_all("td")
                    if len(cells) >= 2:
                        num_text = (await cells[0].inner_text()).strip()
                        status_text = (await cells[1].inner_text()).strip()
                        result["question_statuses"].append({
                            "number": num_text,
                            "status": status_text,
                        })
                        if "Answer saved" not in status_text and "Not yet answered" in status_text:
                            result["has_unanswered"] = True
                        elif "Answer saved" in status_text:
                            pass  # answered
                except Exception:
                    continue

            # Check for submit button
            submit_btn = await page.query_selector('button:has-text("Submit all and finish"), input[value*="Submit all"]')
            result["can_submit"] = submit_btn is not None

        except Exception as e:
            logger.error("Error parsing summary page: %s", e)

        return result
