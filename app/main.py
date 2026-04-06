import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings

# ---------------------------------------------------------------------------
# structlog configuration
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# ---------------------------------------------------------------------------
# Jinja2 templates (shared instance)
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(
        "application_startup",
        env=settings.app_env,
        port=settings.app_port,
        debug=settings.app_debug,
    )
    yield
    logger.info("application_shutdown")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Commercial Vehicle Leaseback Pricing Optimizer",
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    # -- CORS ---------------------------------------------------------------
    allowed_origins: list[str] = [
        f"http://localhost:{settings.app_port}",
        "http://localhost:3000",
    ]
    if settings.supabase_url:
        allowed_origins.append(settings.supabase_url)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Static files -------------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # -- Routers ------------------------------------------------------------
    from app.api import auth, market_prices, masters, pages, simulation  # noqa: E402

    app.include_router(auth.router)
    app.include_router(simulation.router)
    app.include_router(market_prices.router)
    app.include_router(masters.router)
    app.include_router(pages.router)

    # -- Health check -------------------------------------------------------
    @app.get("/health", tags=["ops"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    # -- Favicon ------------------------------------------------------------
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        from fastapi.responses import FileResponse

        ico_path = STATIC_DIR / "favicon.svg"
        if ico_path.exists():
            return FileResponse(str(ico_path), media_type="image/svg+xml")
        return JSONResponse(status_code=204, content=None)

    return app


app = create_app()
