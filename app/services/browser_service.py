"""
app/services/browser_service.py
Playwright browser management service.
Attaches to an existing logged-in browser session using persistent context.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global browser state
_playwright_instance = None
_browser = None
_context = None
_page = None
_lock = asyncio.Lock()


async def get_page():
    """Get the current browser page, creating if needed."""
    global _playwright_instance, _browser, _context, _page
    async with _lock:
        if _page is None or _page.is_closed():
            if _context:
                try:
                    await _context.close()
                except Exception:
                    pass
            if _browser:
                try:
                    await _browser.close()
                except Exception:
                    pass
            if _playwright_instance:
                try:
                    await _playwright_instance.stop()
                except Exception:
                    pass
            _page = None
            _context = None
            _browser = None
            _playwright_instance = None
            await _initialize_browser()
    return _page


async def _initialize_browser() -> None:
    """Initialize Playwright browser with persistent context."""
    global _playwright_instance, _browser, _context, _page
    settings = get_settings()

    from playwright.async_api import async_playwright
    _playwright_instance = await async_playwright().start()
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
    if not settings.browser_headless:
        launch_args.extend([
            "--new-window",
            "--window-position=50,50",
            "--window-size=1280,900",
        ])

    _browser = await _playwright_instance.chromium.launch(
        headless=settings.browser_headless,
        args=launch_args,
    )
    _context = await _browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        ignore_https_errors=True,
    )
    _page = await _context.new_page()
    _page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    try:
        await _page.bring_to_front()
    except Exception:
        pass
    logger.info("Browser initialized (headless=%s)", settings.browser_headless)



async def close_browser() -> None:
    """Close the browser and clean up resources."""
    global _playwright_instance, _browser, _context, _page
    async with _lock:
        if _page and not _page.is_closed():
            await _page.close()
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _playwright_instance:
            await _playwright_instance.stop()
        _page = None
        _context = None
        _browser = None
        _playwright_instance = None
    logger.info("Browser closed")


async def navigate_to(url: str, wait_for: str = "domcontentloaded", timeout_ms: Optional[int] = None) -> None:
    """Navigate the browser to a URL."""
    settings = get_settings()
    page = await get_page()
    t = timeout_ms or settings.browser_timeout_ms
    await page.goto(url, wait_until=wait_for, timeout=t)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    logger.info("Navigated to: %s", url[:100])


async def check_login_required(page=None) -> bool:
    """Check if the current page is a login page."""
    if page is None:
        page = await get_page()
    url = page.url
    return any(kw in url for kw in ["login", "signin", "auth"]) or \
           await page.query_selector('form[action*="login"]') is not None


async def perform_login(username: str, password: str, page=None) -> bool:
    """
    Attempt to log into Moodle using provided username and password.
    Returns True if login appears successful, False otherwise.
    """
    if page is None:
        page = await get_page()
    try:
        logger.info("Attempting automatic Moodle login for user: %s", username)

        # Look for username input
        user_selectors = ["#username", "input[name='username']", "input[name='user']", "input[type='text']"]
        user_input = None
        for sel in user_selectors:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                user_input = sel
                break

        # Look for password input
        pwd_selectors = ["#password", "input[name='password']", "input[type='password']"]
        pwd_input = None
        for sel in pwd_selectors:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                pwd_input = sel
                break

        if not user_input or not pwd_input:
            logger.warning("Could not find username or password inputs on login page")
            return False

        await page.fill(user_input, username)
        await page.fill(pwd_input, password)

        # Look for submit button
        submit_selectors = ["#loginbtn", "button[id='loginbtn']", "button[type='submit']", "input[type='submit']"]
        clicked = False
        for sel in submit_selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                clicked = True
                break

        if not clicked:
            # Fallback: press Enter on password field
            await page.press(pwd_input, "Enter")

        # Wait for navigation / network idle
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            await asyncio.sleep(3)

        # Check if we are still on login page
        still_login = await check_login_required(page)
        if still_login:
            logger.warning("Still on login page after submitting credentials")
            return False

        logger.info("Moodle login successful")
        return True
    except Exception as e:
        logger.error("Error during automatic Moodle login: %s", e)
        return False


async def check_is_moodle_quiz(page=None) -> bool:
    """Verify the page is a Moodle quiz attempt page."""
    if page is None:
        page = await get_page()
    url = page.url
    return "/mod/quiz/attempt.php" in url or "/mod/quiz/summary.php" in url


async def check_and_start_attempt_if_view_page(page=None) -> bool:
    """
    If currently on a quiz view page (/mod/quiz/view.php), check if there is an
    'Attempt quiz now' or 'Continue your attempt' button and click it.
    """
    if page is None:
        page = await get_page()
    if "/mod/quiz/view.php" not in page.url:
        return False
    try:
        start_btn = await page.query_selector(
            'button:has-text("Attempt quiz"), button:has-text("Continue"), '
            'input[value*="Attempt quiz"], input[value*="Continue"], '
            'form[action*="startattempt.php"] button, form[action*="startattempt.php"] input[type="submit"]'
        )
        if start_btn and await start_btn.is_visible():
            logger.info("Found start/continue attempt button on view page, clicking it")
            await start_btn.click()
            # If there is a confirmation modal (e.g., timed quiz 'Start attempt')
            try:
                dialog_btn = await page.wait_for_selector(
                    'input[value="Start attempt"], button:has-text("Start attempt")',
                    timeout=3000
                )
                if dialog_btn and await dialog_btn.is_visible():
                    await dialog_btn.click()
            except Exception:
                pass
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            return True
    except Exception as e:
        logger.debug("Could not start attempt from view page: %s", e)
    return False


async def validate_quiz_url(url: str) -> tuple[bool, str]:
    """
    Validate a quiz URL for safety before navigation.
    Returns (is_valid, error_message).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    if parsed.scheme not in ("http", "https"):
        return False, "URL must use http or https"

    # SSRF protection: block private/loopback IPs (allow localhost for dev)
    host = parsed.hostname or ""
    private_patterns = [
        r"^10\.", r"^172\.(1[6-9]|2\d|3[01])\.", r"^192\.168\.",
        r"^127\.", r"^0\.", r"^169\.254\.", r"^\[::1\]", r"^fc", r"^fd",
    ]
    # Allow localhost for development
    if host not in ("localhost", "127.0.0.1"):
        for pattern in private_patterns[2:]:  # Skip 10.x and 172.x blocking for university IPs
            if re.match(pattern, host):
                return False, f"Private/loopback IP addresses are not allowed: {host}"

    # Must be a Moodle quiz URL
    if "quiz" not in url.lower() and "moodle" not in url.lower():
        logger.warning("URL does not appear to be a Moodle quiz URL: %s", url[:100])
        # Don't block — user may know what they're doing

    return True, ""


async def click_next_page(page=None) -> bool:
    """Click the 'Next page' button. Returns True if clicked."""
    if page is None:
        page = await get_page()
    try:
        selectors = [
            'input[name="next"]',
            'button:has-text("Next page")',
            'input[value="Next page"]',
            '.submitbtns input[name="next"]',
        ]
        for sel in selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                return True
    except Exception as e:
        logger.error("Error clicking next page: %s", e)
    return False


async def click_finish_attempt(page=None) -> bool:
    """Click 'Finish attempt' button to go to summary page. Returns True if clicked."""
    if page is None:
        page = await get_page()
    try:
        selectors = [
            'input[name="finishattempt"]',
            'button:has-text("Finish attempt")',
            'a:has-text("Finish attempt")',
        ]
        for sel in selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                return True
    except Exception as e:
        logger.error("Error clicking Finish attempt: %s", e)
    return False


async def select_radio_option(page, question_block, option_value: str) -> bool:
    """Select a radio button option by value or id."""
    try:
        radio = await question_block.query_selector(f'input[type="radio"][value="{option_value}"]')
        if not radio:
            radio = await question_block.query_selector(f'[id="{option_value}"]')
        if radio:
            await radio.scroll_into_view_if_needed()
            await radio.click(force=True)
            await page.wait_for_timeout(300)
            return True
    except Exception as e:
        logger.error("Error selecting radio option %s: %s", option_value, e)
    return False


async def select_checkbox_option(page, question_block, option_value: str, check: bool = True) -> bool:
    """Check or uncheck a checkbox option by value or id."""
    try:
        cb = await question_block.query_selector(f'input[type="checkbox"][value="{option_value}"]')
        if not cb:
            cb = await question_block.query_selector(f'[id="{option_value}"]')
        if cb:
            await cb.scroll_into_view_if_needed()
            is_checked = await cb.is_checked()
            if (check and not is_checked) or (not check and is_checked):
                await cb.click(force=True)
                await page.wait_for_timeout(200)
            return True
    except Exception as e:
        logger.error("Error selecting checkbox option %s: %s", option_value, e)
    return False


async def submit_quiz_final(page=None) -> bool:
    """
    Handle the final quiz submission with confirmation dialog.
    Finds and clicks 'Submit all and finish' on the summary page,
    then confirms in the modal dialog.
    """
    if page is None:
        page = await get_page()

    try:
        # Step 1: Find candidate 'Submit all and finish' buttons on the summary page.
        # CRITICAL: Exclude 'Return to attempt'!
        candidates = await page.query_selector_all(
            'form[action*="processattempt"] button, '
            'form[action*="processattempt"] input[type="submit"], '
            'button:has-text("Submit all and finish"), '
            'input[value*="Submit all and finish"], '
            'button:has-text("Submit all"), '
            'input[value*="Submit all"]'
        )

        summary_submit = None
        for el in candidates:
            try:
                # Discard if inside an unopened modal dialog
                in_modal = await el.evaluate("node => !!node.closest('.modal:not(.show), [role=\"dialog\"][aria-hidden=\"true\"]')")
                if in_modal:
                    continue

                text = (await el.inner_text() or "").strip().lower()
                val = (await el.get_attribute("value") or "").strip().lower()

                # MUST NOT be "Return to attempt"
                if "return" in text or "return" in val:
                    continue

                if "submit" in text or "submit" in val or "finish" in text or "finish" in val or not (text or val):
                    if await el.is_visible():
                        summary_submit = el
                        break
            except Exception:
                continue

        # Fallback: find any candidate where "return" is NOT in text
        if not summary_submit:
            for el in candidates:
                try:
                    text = (await el.inner_text() or "").strip().lower()
                    val = (await el.get_attribute("value") or "").strip().lower()
                    if "return" not in text and "return" not in val:
                        summary_submit = el
                        break
                except Exception:
                    continue

        if not summary_submit:
            logger.warning("Submit all and finish button not found on summary page")
            return False

        btn_text = (await summary_submit.inner_text() or "").strip()
        logger.info("Found summary submit button (text: %r)", btn_text)

        # Click the summary page button
        try:
            await summary_submit.scroll_into_view_if_needed()
            await summary_submit.click(timeout=5000)
        except Exception as e:
            logger.info("Direct click failed (%s), clicking via DOM evaluation...", e)
            await summary_submit.evaluate("node => node.click()")

        logger.info("Clicked 'Submit all and finish' button on summary page")
        await page.wait_for_timeout(1500)

        # Step 2: Handle confirmation dialog
        dialog = None
        for selector in ['.modal.show', '[role="dialog"]:not([aria-hidden="true"])', '[data-region="modal"]', '.moodle-dialogue-base', '.modal']:
            try:
                el = await page.wait_for_selector(selector, timeout=3500)
                if el and await el.is_visible():
                    dialog = el
                    break
            except Exception:
                continue

        if dialog:
            logger.info("Confirmation dialog detected")
            confirm_candidates = await dialog.query_selector_all(
                'button:has-text("Submit all and finish"), input[value*="Submit all and finish"], '
                '.modal-footer .btn-primary, button.btn-primary, input.btn-primary, '
                'button[data-action="save"], button:has-text("Submit all"), button[type="submit"]'
            )
            confirm_btn = None
            for c_btn in confirm_candidates:
                try:
                    c_text = (await c_btn.inner_text() or "").lower()
                    if "cancel" in c_text or "close" in c_text:
                        continue
                    if await c_btn.is_visible():
                        confirm_btn = c_btn
                        break
                except Exception:
                    continue

            if not confirm_btn and confirm_candidates:
                confirm_btn = confirm_candidates[0]

            if confirm_btn:
                try:
                    await confirm_btn.scroll_into_view_if_needed()
                    await confirm_btn.click(timeout=5000, force=True)
                except Exception as e:
                    logger.info("Modal confirm click failed (%s), clicking via DOM evaluation...", e)
                    await confirm_btn.evaluate("node => node.click()")

                logger.info("Confirmed submission in modal dialog")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    await page.wait_for_timeout(4000)
                return True
            else:
                logger.warning("Confirm button not found in modal dialog")

        # Step 3: If modal was not shown or didn't complete, submit the processattempt form directly
        process_form = await page.query_selector('form[action*="processattempt"]')
        if process_form:
            logger.info("Submitting processattempt form directly via DOM...")
            await process_form.evaluate("f => f.submit()")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                await page.wait_for_timeout(4000)
            return True

        # Verify if redirected to review page
        await page.wait_for_timeout(3000)
        final_url = page.url
        if "review.php" in final_url or "view.php" in final_url:
            logger.info("Quiz submitted (URL: %s)", final_url)
            return True

        return False

    except Exception as e:
        logger.error("Error during final submission: %s", e)
        return False




async def get_page_state(page=None) -> dict:
    """Get current page state information."""
    if page is None:
        page = await get_page()
    return {
        "url": page.url,
        "title": await page.title(),
        "is_quiz": await check_is_moodle_quiz(page),
        "login_required": await check_login_required(page),
    }
