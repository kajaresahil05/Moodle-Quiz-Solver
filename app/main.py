"""
app/main.py
FastAPI application entry point.
"""
from __future__ import annotations

import asyncio
import logging
import sys

# On Windows, Playwright requires ProactorEventLoop for subprocess support.
# Uvicorn on Windows defaults or switches to SelectorEventLoop, which causes NotImplementedError.
if sys.platform == "win32":
    try:
        import uvicorn.loops.asyncio
        uvicorn.loops.asyncio.asyncio_setup = lambda use_subprocess=False: None
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass


from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app import database as db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("quiz_assistant.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting Moodle Quiz Assistant...")
    settings = get_settings()

    # Initialize database
    db.init_db()
    logger.info("Database ready")

    if not settings.gemini_configured:
        logger.warning(
            "GEMINI_API_KEY not configured. Copy .env.example to .env and set your key."
        )

    yield

    # Shutdown: close browser
    logger.info("Shutting down...")
    try:
        from app.services import browser_service
        await browser_service.close_browser()
    except Exception as e:
        logger.error("Error closing browser: %s", e)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Gemini-Powered Moodle Quiz Assistant",
        description="Automated practice-quiz assistance with AI suggestions",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Accept"],
    )

    # Static files
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # Include routers
    from app.routes import auth, dashboard, workflows, settings as settings_router
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(workflows.router)
    app.include_router(settings_router.router)

    # Redirects for standard documentation paths
    @app.get("/docs", include_in_schema=False)
    async def docs_redirect():
        return RedirectResponse(url="/api/docs")

    @app.get("/redoc", include_in_schema=False)
    async def redoc_redirect():
        return RedirectResponse(url="/api/redoc")

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred. Check logs for details."},
        )

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_level="info",
    )
