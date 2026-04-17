"""Prometheus metrics + SLA logging middleware.

Exposes two module-level Prometheus collectors (registered on the default
global registry) and two Starlette-style HTTP middlewares:

* ``metrics_middleware`` — increments ``http_requests_total`` and observes
  ``http_request_duration_seconds`` on every request.
* ``sla_logging_middleware`` — logs a ``sla_breach`` warning when a request
  exceeds ``SLA_THRESHOLD_MS`` (default 2000 ms). The threshold can be
  overridden at runtime (useful for tests) by setting
  ``app.middleware.metrics.SLA_THRESHOLD_MS`` to a different value.
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus collectors
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by the application.",
    labelnames=("method", "path", "status"),
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    labelnames=("method", "path"),
    # Reasonable default buckets for a web app (5ms..10s).
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# SLA threshold (mutable at runtime so tests can override)
# ---------------------------------------------------------------------------

SLA_THRESHOLD_MS: float = 2000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_pattern(request: Request) -> str:
    """Return the matched route's path template if available.

    Falls back to ``request.url.path`` for unmatched routes. Using the route
    pattern (e.g. ``/invoices/{id}``) keeps cardinality low so Prometheus
    label explosion does not occur on id-bearing paths.
    """
    route = request.scope.get("route")
    # Starlette's Route has ``path`` (template) and Mount has ``path`` too.
    path = getattr(route, "path", None)
    if path:
        return path
    return request.url.path


# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------


class metrics_middleware(BaseHTTPMiddleware):  # noqa: N801 — referenced by name
    """Record request counter + duration histogram for every request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            path = _route_pattern(request)
            method = request.method
            try:
                http_requests_total.labels(
                    method=method, path=path, status=str(status_code)
                ).inc()
                http_request_duration_seconds.labels(
                    method=method, path=path
                ).observe(duration)
            except Exception:  # pragma: no cover — never let metrics break a request
                logger.exception("metrics_record_failed", path=path)


class sla_logging_middleware(BaseHTTPMiddleware):  # noqa: N801
    """Emit a structured warning when a request exceeds the SLA threshold."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            if duration_ms > SLA_THRESHOLD_MS:
                user_id = None
                # Best-effort extraction of the authenticated user id without
                # coupling to a specific auth middleware.
                user = getattr(request.state, "user", None)
                if user is not None:
                    user_id = getattr(user, "id", None) or (
                        user.get("id") if isinstance(user, dict) else None
                    )
                logger.warning(
                    "sla_breach",
                    path=_route_pattern(request),
                    method=request.method,
                    duration_ms=round(duration_ms, 2),
                    user_id=user_id,
                )
