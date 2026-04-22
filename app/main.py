import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
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
# App metadata
# ---------------------------------------------------------------------------

APP_VERSION = "0.1.0"
_APP_START_TIME = time.time()

# ---------------------------------------------------------------------------
# Sentry (optional) — guarded import, no-op when DSN unset
# ---------------------------------------------------------------------------

_SENTRY_ENABLED = False


def _init_sentry() -> None:
    """Initialise the Sentry SDK if ``settings.sentry_dsn`` is set.

    The import is guarded so that environments without the ``sentry-sdk``
    package (or without a DSN) incur zero overhead and no ImportError.
    This function is called once at module import time.

    The entire body is additionally wrapped in try/except so that any
    unexpected failure (settings, environment, etc.) cannot crash app
    boot on serverless platforms such as Vercel.
    """
    global _SENTRY_ENABLED

    try:
        settings = get_settings()
        dsn = settings.sentry_dsn
        if not dsn:
            return

        try:  # guarded import — sentry is optional
            import sentry_sdk  # noqa: F401
        except Exception as exc:  # pragma: no cover — library missing
            logger.warning("sentry_import_failed", error=str(exc))
            return

        try:
            sentry_sdk.init(
                dsn=dsn,
                environment=settings.app_env,
                traces_sample_rate=settings.sentry_traces_sample_rate,
                profiles_sample_rate=0.0,
                release=os.getenv("SENTRY_RELEASE"),
            )
            _SENTRY_ENABLED = True
            logger.info("sentry_initialized", environment=settings.app_env)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("sentry_init_failed", error=str(exc))
    except Exception as exc:  # pragma: no cover — outermost guard
        logger.warning("sentry_init_outer_failed", error=str(exc))


# Initialise Sentry once at module load. Safe no-op when DSN is empty.
_init_sentry()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

import os as _os

# On Vercel, __file__ may resolve differently. Use multiple fallbacks.
_this_file = Path(__file__).resolve()
APP_DIR = _this_file.parent
BASE_DIR = APP_DIR.parent

# Try multiple candidate paths for templates and static
_template_candidates = [
    APP_DIR / "templates",
    BASE_DIR / "app" / "templates",
    Path(_os.getcwd()) / "app" / "templates",
]
TEMPLATES_DIR = next((p for p in _template_candidates if p.is_dir()), _template_candidates[0])

_static_candidates = [
    BASE_DIR / "static",
    Path(_os.getcwd()) / "static",
]
STATIC_DIR = next((p for p in _static_candidates if p.is_dir()), _static_candidates[0])

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

    # -- Background scheduler (monthly invoice cron, etc.) ---------------
    # Vercel serverless has no persistent process, so APScheduler cannot
    # run there. Also honor an explicit opt-out via SKIP_SCHEDULER=1.
    # The scheduler import itself is guarded: a missing apscheduler wheel
    # must never crash application boot.
    scheduler = None
    scheduler_enabled = (
        os.getenv("VERCEL") != "1" and os.getenv("SKIP_SCHEDULER") != "1"
    )

    start_scheduler = None
    shutdown_scheduler = None
    if scheduler_enabled:
        try:
            from app.core.scheduler import (
                shutdown_scheduler,
                start_scheduler,
            )
        except ImportError as exc:
            logger.warning("scheduler_import_failed", error=str(exc))
            start_scheduler = None
            shutdown_scheduler = None

        if start_scheduler is not None:
            try:
                scheduler = start_scheduler()
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("scheduler_start_failed", error=str(exc))
                scheduler = None
    else:
        logger.info(
            "scheduler_skipped",
            vercel=os.getenv("VERCEL"),
            skip_scheduler=os.getenv("SKIP_SCHEDULER"),
        )

    app.state.scheduler = scheduler

    try:
        yield
    finally:
        if scheduler is not None and shutdown_scheduler is not None:
            try:
                shutdown_scheduler(scheduler)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("scheduler_shutdown_failed", error=str(exc))
        logger.info("application_shutdown")


# ---------------------------------------------------------------------------
# Health check helpers
# ---------------------------------------------------------------------------


async def _check_database(timeout_s: float = 0.5) -> str:
    """Trivial supabase reachability check with a hard timeout.

    Returns ``"ok"`` on success, ``"degraded"`` on timeout/error. Never
    raises — the health endpoint should report degradation, not crash.
    """

    def _probe() -> bool:
        from app.db.supabase_client import get_supabase_client

        client = get_supabase_client()
        # Cheap round-trip: limit=1, no rows required.
        client.table("users").select("id").limit(1).execute()
        return True

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe), timeout=timeout_s)
        return "ok"
    except Exception:
        return "degraded"


def _check_scheduler(app: FastAPI) -> str:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return "not_configured"
    try:
        running = bool(getattr(scheduler, "running", False))
    except Exception:
        return "degraded"
    return "ok" if running else "degraded"


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Commercial Vehicle Leaseback Pricing Optimizer",
        version=APP_VERSION,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware registration order
    #
    # Starlette applies middleware in REVERSE order of registration: the
    # LAST middleware registered is the OUTERMOST wrapper. We want the
    # effective request/response pipeline to be (outer -> inner):
    #
    #   Sentry -> metrics -> SLA -> CORS -> CSRF -> RateLimit
    #     -> SecurityHeaders -> route
    #
    # so we register in the reverse of that order below.
    # ------------------------------------------------------------------

    # -- Security headers (innermost middleware) -----------------------
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # -- Rate limiting (SlowAPI) ---------------------------------------
    # SlowAPI is listed in pyproject but we still guard defensively so
    # that a missing wheel on Vercel can never 500 the whole app.
    try:
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware

        from app.middleware.rate_limit import limiter

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)
    except ImportError as exc:
        logger.warning("slowapi_import_failed", error=str(exc))

    # -- CSRF -----------------------------------------------------------
    from app.middleware.csrf import CSRFMiddleware
    app.add_middleware(CSRFMiddleware)

    # -- CORS -----------------------------------------------------------
    from app.config import parse_allowed_origins
    allowed_origins: list[str] = [
        f"http://localhost:{settings.app_port}",
        "http://localhost:3000",
        "https://auction-ten-iota.vercel.app",
    ]
    allowed_origins.extend(parse_allowed_origins(settings.cors_allowed_origins))
    allowed_origins.extend(parse_allowed_origins(settings.allowed_origins))
    if settings.supabase_url:
        allowed_origins.append(settings.supabase_url)
    allowed_origins = list(dict.fromkeys(allowed_origins))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-CSRF-Token",
            "HX-Request",
            "HX-Target",
            "HX-Current-URL",
        ],
    )

    # -- SLA logging + Prometheus metrics ------------------------------
    # Metrics middleware depends on prometheus_client which is optional
    # in some deployment environments (e.g. slim serverless images).
    _metrics_available = False
    try:
        from app.middleware.metrics import (
            metrics_middleware,
            sla_logging_middleware,
        )

        app.add_middleware(sla_logging_middleware)
        app.add_middleware(metrics_middleware)
        _metrics_available = True
    except ImportError as exc:
        logger.warning("metrics_import_failed", error=str(exc))

    # -- Static files ---------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # -- Routers ------------------------------------------------------------
    from app.api import auth, contracts, dashboard, esg, financial, investor_reports, invoices, lease_contracts, liquidation, ltv, market_prices, masters, pages, pricing, privacy, proposals, simulation, telemetry, value_transfer, vehicle_nav, yayoi  # noqa: E402

    app.include_router(auth.router)
    app.include_router(contracts.router)
    app.include_router(dashboard.router)
    app.include_router(esg.router)
    app.include_router(financial.router)
    app.include_router(investor_reports.router)
    app.include_router(invoices.router)
    app.include_router(lease_contracts.router)
    app.include_router(liquidation.router)
    app.include_router(ltv.router)
    app.include_router(pricing.router)
    app.include_router(privacy.router)
    app.include_router(proposals.router)
    app.include_router(simulation.router)
    app.include_router(market_prices.router)
    app.include_router(telemetry.router)
    app.include_router(value_transfer.router)
    app.include_router(vehicle_nav.router)
    app.include_router(masters.router)
    app.include_router(pages.router)
    app.include_router(yayoi.router)

    # -- Health checks --------------------------------------------------
    @app.get("/health", tags=["ops"])
    async def health_check() -> JSONResponse:
        """Liveness-style health endpoint.

        Always returns 200 — it reports status ("ok" / "degraded") in
        the body but never fails the HTTP response. Readiness semantics
        (503 on failure) live at ``/health/ready``.
        """
        try:
            checks = {
                "database": await _check_database(),
                "scheduler": _check_scheduler(app),
            }
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("health_check_probe_failed", error=str(exc))
            checks = {"database": "degraded", "scheduler": "degraded"}
        ok_values = {"ok", "not_configured"}
        status = "ok" if all(v in ok_values for v in checks.values()) else "degraded"
        payload = {
            "status": status,
            "version": APP_VERSION,
            "checks": checks,
            "timestamp": time.time(),
        }
        return JSONResponse(status_code=200, content=payload)

    @app.get("/health/ready", tags=["ops"])
    async def health_ready() -> JSONResponse:
        """Readiness probe — 503 if ANY check is not ok."""
        checks = {
            "database": await _check_database(),
            "scheduler": _check_scheduler(app),
        }
        ok_values = {"ok", "not_configured"}
        all_ok = all(v in ok_values for v in checks.values())
        payload = {
            "status": "ok" if all_ok else "degraded",
            "version": APP_VERSION,
            "checks": checks,
            "timestamp": time.time(),
        }
        return JSONResponse(status_code=200 if all_ok else 503, content=payload)

    @app.get("/health/live", tags=["ops"])
    async def health_live() -> dict:
        """Liveness probe — always 200, reports uptime."""
        return {
            "status": "ok",
            "version": APP_VERSION,
            "uptime_seconds": round(time.time() - _APP_START_TIME, 3),
            "timestamp": time.time(),
        }

    # -- Prometheus metrics endpoint -----------------------------------
    # NOTE: intentionally unauthenticated (typical for internal scrape
    # targets). In production this endpoint MUST be firewall-gated or
    # placed behind a reverse-proxy ACL so it is not publicly exposed.
    @app.get("/metrics", tags=["metrics"], include_in_schema=False)
    async def metrics_endpoint() -> Response:
        if not _metrics_available:
            return Response(
                content="prometheus_client unavailable",
                status_code=503,
                media_type="text/plain",
            )
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        except ImportError as exc:
            logger.warning("prometheus_import_failed", error=str(exc))
            return Response(
                content="prometheus_client unavailable",
                status_code=503,
                media_type="text/plain",
            )

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # -- Favicon --------------------------------------------------------
    # Accept HEAD too — browsers + health checkers probe with HEAD before GET.
    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    async def favicon():
        from fastapi.responses import FileResponse

        ico_path = STATIC_DIR / "favicon.svg"
        if ico_path.exists():
            return FileResponse(str(ico_path), media_type="image/svg+xml")
        return JSONResponse(status_code=204, content=None)

    # -- Sentry ASGI wrapper (outermost) -------------------------------
    # Registered last so it wraps every other middleware. Guarded: only
    # wired up when the SDK import + init succeeded.
    if _SENTRY_ENABLED:
        try:
            from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

            app.add_middleware(SentryAsgiMiddleware)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("sentry_asgi_wrap_failed", error=str(exc))

    return app


app = create_app()
