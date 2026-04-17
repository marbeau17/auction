"""Unit tests for app/middleware/metrics.py.

Covers:
* ``http_requests_total`` Counter increments after a real request.
* ``http_request_duration_seconds`` Histogram observes a duration.
* ``sla_logging_middleware`` emits a ``sla_breach`` warning when a
  request exceeds the (overridable) SLA threshold.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.middleware import metrics as metrics_mod
from app.middleware.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    metrics_middleware,
    sla_logging_middleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(register_sla: bool = False, register_metrics: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    @app.get("/slow")
    async def slow() -> dict:
        # Deliberately slow — test will override SLA threshold.
        await asyncio.sleep(0.01)
        return {"ok": True}

    # Registration order: sla_logging first (innermost), metrics last
    # (outermost) — matches main.py.
    if register_sla:
        app.add_middleware(sla_logging_middleware)
    if register_metrics:
        app.add_middleware(metrics_middleware)
    return app


def _counter_value(method: str, path: str, status: str) -> float:
    """Read http_requests_total{method,path,status} via the public registry."""
    value = REGISTRY.get_sample_value(
        "http_requests_total",
        labels={"method": method, "path": path, "status": status},
    )
    return 0.0 if value is None else float(value)


def _histogram_count(method: str, path: str) -> float:
    """Total observation count for http_request_duration_seconds."""
    value = REGISTRY.get_sample_value(
        "http_request_duration_seconds_count",
        labels={"method": method, "path": path},
    )
    return 0.0 if value is None else float(value)


def _histogram_sum(method: str, path: str) -> float:
    """Sum of all observations for http_request_duration_seconds."""
    value = REGISTRY.get_sample_value(
        "http_request_duration_seconds_sum",
        labels={"method": method, "path": path},
    )
    return 0.0 if value is None else float(value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_counter_increments_after_request() -> None:
    """After a request, http_requests_total for that label set is +1."""
    app = _build_app()
    client = TestClient(app)

    before = _counter_value("GET", "/ping", "200")
    resp = client.get("/ping")
    assert resp.status_code == 200
    after = _counter_value("GET", "/ping", "200")
    assert after == pytest.approx(before + 1.0)


def test_histogram_records_duration() -> None:
    """After a request, the histogram count AND sum increase."""
    app = _build_app()
    client = TestClient(app)

    before_count = _histogram_count("GET", "/ping")
    before_sum = _histogram_sum("GET", "/ping")

    resp = client.get("/ping")
    assert resp.status_code == 200

    after_count = _histogram_count("GET", "/ping")
    after_sum = _histogram_sum("GET", "/ping")

    assert after_count == pytest.approx(before_count + 1.0)
    # A real request always takes > 0 seconds.
    assert after_sum > before_sum


def test_sla_warning_triggered_for_slow_request(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Request exceeding the overridden threshold emits a warning.

    We monkey-patch the middleware module's logger to a stdlib logger that
    caplog can intercept — this keeps the test independent of whichever
    structlog configuration is active in the surrounding process.
    """
    # 5 ms threshold, and /slow sleeps for 10 ms.
    monkeypatch.setattr(metrics_mod, "SLA_THRESHOLD_MS", 5.0)

    # Route structlog warnings through a stdlib logger caplog can see.
    stdlib_logger = logging.getLogger("test.metrics")
    stdlib_logger.setLevel(logging.WARNING)

    class _Shim:
        def warning(self, event: str, **kw: object) -> None:
            stdlib_logger.warning("%s %s", event, kw)

        def exception(self, event: str, **kw: object) -> None:  # pragma: no cover
            stdlib_logger.exception("%s %s", event, kw)

    monkeypatch.setattr(metrics_mod, "logger", _Shim())

    app = _build_app(register_sla=True, register_metrics=False)
    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="test.metrics"):
        resp = client.get("/slow")
        assert resp.status_code == 200

    messages = [rec.getMessage() for rec in caplog.records]
    assert any("sla_breach" in m for m in messages), (
        f"expected sla_breach warning; got {messages!r}"
    )
    assert any("duration_ms" in m for m in messages)


def test_sla_warning_not_triggered_for_fast_request(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request under threshold does NOT emit sla_breach."""
    # Threshold well above any realistic request duration.
    monkeypatch.setattr(metrics_mod, "SLA_THRESHOLD_MS", 60_000.0)

    stdlib_logger = logging.getLogger("test.metrics.fast")
    stdlib_logger.setLevel(logging.WARNING)

    class _Shim:
        def warning(self, event: str, **kw: object) -> None:
            stdlib_logger.warning("%s %s", event, kw)

        def exception(self, event: str, **kw: object) -> None:  # pragma: no cover
            stdlib_logger.exception("%s %s", event, kw)

    monkeypatch.setattr(metrics_mod, "logger", _Shim())

    app = _build_app(register_sla=True, register_metrics=False)
    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="test.metrics.fast"):
        resp = client.get("/ping")
        assert resp.status_code == 200

    messages = [rec.getMessage() for rec in caplog.records]
    assert not any("sla_breach" in m for m in messages), (
        f"did not expect sla_breach warning; got {messages!r}"
    )
