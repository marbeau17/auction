"""Vehicle telemetry ingest & read API (Phase-3a foundation).

Scope:
* POST /api/v1/telemetry/ingest          — single-event ingest (device token)
* POST /api/v1/telemetry/ingest/batch    — up to 500 events per request
* GET  /api/v1/telemetry/{vehicle_id}/recent?limit=
* GET  /api/v1/telemetry/{vehicle_id}/daily?start=&end=

Streaming (MQTT / Kafka / Redis Streams) is explicitly out of scope; see
docs/telemetry_roadmap.md section 3.3.
"""

from __future__ import annotations

import hmac
from datetime import date
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from supabase import Client

from app.config import Settings, get_settings
from app.db.repositories.telemetry_repo import TelemetryRepository
from app.dependencies import get_supabase_client
from app.middleware.rbac import require_permission
from app.models.common import SuccessResponse
from app.models.telemetry import (
    TelemetryAggregate,
    TelemetryBatchRequest,
    TelemetryEvent,
    TelemetryIngestResult,
    TelemetryResponse,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


# ---------------------------------------------------------------------------
# Auth for the ingest endpoints
# ---------------------------------------------------------------------------


async def _require_device_token(
    x_device_token: Optional[str] = Header(
        default=None,
        alias="X-Device-Token",
        description="Shared secret issued to the telematics device / gateway",
    ),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the ``X-Device-Token`` header against ``TELEMETRY_INGEST_TOKEN``.

    This is the ingest-side equivalent of ``app.dependencies.require_role``;
    it guards the two ``/ingest`` endpoints. A constant-time comparison is
    used so the token value cannot be inferred via timing.

    The expected token is taken from the ``TELEMETRY_INGEST_TOKEN`` Settings
    field (env var of the same name). If the server has no token configured,
    the endpoint refuses all requests — fail-closed.
    """
    expected = (settings.telemetry_ingest_token or "").strip()
    if not expected:
        logger.error("telemetry_ingest_token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry ingest is not configured on this server",
        )
    provided = (x_device_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing device token",
        )
    return provided


def _get_repo(
    supabase: Client = Depends(get_supabase_client),
) -> TelemetryRepository:
    return TelemetryRepository(client=supabase)


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TelemetryIngestResult,
)
async def ingest_event(
    event: TelemetryEvent,
    _: str = Depends(_require_device_token),
    repo: TelemetryRepository = Depends(_get_repo),
) -> TelemetryIngestResult:
    """Ingest a single telemetry event.

    Authentication: ``X-Device-Token`` header must match
    ``TELEMETRY_INGEST_TOKEN`` (fail-closed if unset).
    """
    try:
        await repo.insert_event(event.model_dump(mode="json"))
        return TelemetryIngestResult(accepted=1, rejected=0)
    except Exception as exc:
        logger.exception(
            "telemetry_ingest_failed",
            vehicle_id=str(event.vehicle_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist telemetry event: {exc}",
        )


# ---------------------------------------------------------------------------
# POST /ingest/batch
# ---------------------------------------------------------------------------


@router.post(
    "/ingest/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TelemetryIngestResult,
)
async def ingest_event_batch(
    payload: TelemetryBatchRequest,
    _: str = Depends(_require_device_token),
    repo: TelemetryRepository = Depends(_get_repo),
) -> TelemetryIngestResult:
    """Bulk ingest up to 500 telemetry events (array in ``events``).

    Validation of ``max_length=500`` is enforced by ``TelemetryBatchRequest``;
    over-size requests are rejected by FastAPI with 422 before reaching this
    handler.
    """
    events_as_dicts = [e.model_dump(mode="json") for e in payload.events]
    try:
        inserted = await repo.insert_events(events_as_dicts)
        return TelemetryIngestResult(
            accepted=len(inserted),
            rejected=len(events_as_dicts) - len(inserted),
        )
    except Exception as exc:
        logger.exception(
            "telemetry_batch_ingest_failed",
            count=len(events_as_dicts),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist telemetry batch: {exc}",
        )


# ---------------------------------------------------------------------------
# GET /{vehicle_id}/recent
# ---------------------------------------------------------------------------


@router.get("/{vehicle_id}/recent", response_model=SuccessResponse)
async def get_recent_events(
    vehicle_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    repo: TelemetryRepository = Depends(_get_repo),
    _user: dict[str, Any] = Depends(require_permission("vehicle_inventory", "read")),
) -> SuccessResponse:
    """Return the most recent ``limit`` telemetry events for a vehicle."""
    rows = await repo.list_recent(vehicle_id=vehicle_id, limit=limit)
    # Cast through the response model to guarantee shape / validation.
    data = [TelemetryResponse.model_validate(r).model_dump(mode="json") for r in rows]
    return SuccessResponse(
        data=data,
        meta={"vehicle_id": str(vehicle_id), "count": len(data), "limit": limit},
    )


# ---------------------------------------------------------------------------
# GET /{vehicle_id}/daily
# ---------------------------------------------------------------------------


@router.get("/{vehicle_id}/daily", response_model=SuccessResponse)
async def get_daily_aggregates(
    vehicle_id: UUID,
    start: date = Query(..., description="Start date (inclusive)"),
    end: date = Query(..., description="End date (inclusive)"),
    repo: TelemetryRepository = Depends(_get_repo),
    _user: dict[str, Any] = Depends(require_permission("vehicle_inventory", "read")),
) -> SuccessResponse:
    """Return daily telemetry aggregates for a vehicle within a date range."""
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`end` must be on or after `start`",
        )
    rows = await repo.daily_aggregate(
        vehicle_id=vehicle_id, start=start, end=end
    )
    data = [TelemetryAggregate.model_validate(r).model_dump(mode="json") for r in rows]
    return SuccessResponse(
        data=data,
        meta={
            "vehicle_id": str(vehicle_id),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "count": len(data),
        },
    )
