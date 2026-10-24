"""
run.py
Convenient entry point to start the Moodle Quiz Assistant.
Ensures WindowsProactorEventLoopPolicy is permanently active for Playwright.
"""
from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    try:
        import uvicorn.loops.asyncio
        uvicorn.loops.asyncio.asyncio_setup = lambda use_subprocess=False: None
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import os
import uvicorn
from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    host = os.environ.get("HOST", os.environ.get("APP_HOST", settings.app_host))
    port = int(os.environ.get("PORT", os.environ.get("APP_PORT", str(settings.app_port))))
    uvicorn.run("app.main:app", host=host, port=port, loop="asyncio")
