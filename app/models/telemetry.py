"""Pydantic models for Phase-3a vehicle telemetry ingestion.

Covers the REST ingest foundation only — the streaming / MQTT path is a
future phase (see docs/telemetry_roadmap.md section 3.3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Ingest (write) models
# ---------------------------------------------------------------------------


class TelemetryEvent(BaseModel):
    """A single telemetry sample ingested from a device.

    ``odometer_km`` monotonicity is validated as a *warning* — the repository
    logs a structured warning but does not reject the payload, because GPS
    resets and device swaps can legitimately break monotonicity.
    """

    vehicle_id: UUID = Field(..., description="Owning vehicle UUID")
    device_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Vendor device identifier",
        examples=["DEV-20260101-0001"],
    )
    recorded_at: datetime = Field(
        ...,
        description="Device-side timestamp of the sample",
        examples=["2026-04-17T10:30:00+09:00"],
    )
    odometer_km: Optional[int] = Field(
        default=None,
        ge=0,
        description="Cumulative odometer reading in km",
        examples=[245320],
    )
    fuel_level_pct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Fuel tank level (%)",
    )
    engine_hours: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Cumulative engine operating hours",
    )
    location_geojson: Optional[dict[str, Any]] = Field(
        default=None,
        description='GeoJSON Point: {"type":"Point","coordinates":[lng,lat]}',
    )
    dtc_codes: list[str] = Field(
        default_factory=list,
        description="Active Diagnostic Trouble Codes",
        examples=[["P0401", "U0100"]],
    )
    raw_payload: Optional[dict[str, Any]] = Field(
        default=None,
        description="Full vendor payload for audit",
    )

    # -- Validators ---------------------------------------------------------

    @field_validator("dtc_codes", mode="before")
    @classmethod
    def _uppercase_dtc_codes(cls, value: Any) -> Any:
        """Normalise DTC codes to uppercase and strip blanks."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("dtc_codes must be a list of strings")
        cleaned: list[str] = []
        for code in value:
            if code is None:
                continue
            s = str(code).strip().upper()
            if s:
                cleaned.append(s)
        return cleaned

    @model_validator(mode="after")
    def _validate_geojson_shape(self) -> "TelemetryEvent":
        """Light sanity check on GeoJSON Point (non-fatal keys allowed)."""
        loc = self.location_geojson
        if loc is None:
            return self
        if not isinstance(loc, dict):
            raise ValueError("location_geojson must be a JSON object")
        if loc.get("type") and loc.get("type") != "Point":
            # Only Point is supported in Phase 3a
            raise ValueError("location_geojson.type must be 'Point'")
        coords = loc.get("coordinates")
        if coords is not None:
            if (
                not isinstance(coords, (list, tuple))
                or len(coords) < 2
                or not all(isinstance(c, (int, float)) for c in coords[:2])
            ):
                raise ValueError(
                    "location_geojson.coordinates must be [lng, lat]"
                )
        return self


class TelemetryBatchRequest(BaseModel):
    """Batch ingest wrapper — capped at 500 events per request."""

    events: list[TelemetryEvent] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Telemetry events to ingest (max 500)",
    )


# ---------------------------------------------------------------------------
# Response (read) models
# ---------------------------------------------------------------------------


class TelemetryResponse(BaseModel):
    """A persisted telemetry event, returned from list endpoints."""

    id: UUID
    vehicle_id: UUID
    device_id: str
    recorded_at: datetime
    odometer_km: Optional[int] = None
    fuel_level_pct: Optional[float] = None
    engine_hours: Optional[float] = None
    location_geojson: Optional[dict[str, Any]] = None
    dtc_codes: list[str] = Field(default_factory=list)
    raw_payload: Optional[dict[str, Any]] = None
    created_at: datetime


class TelemetryAggregate(BaseModel):
    """Daily rollup row (written by a future rollup job, read via API)."""

    vehicle_id: UUID
    agg_date: date
    km_driven: int = Field(ge=0, default=0)
    avg_fuel_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    engine_hours_delta: float = Field(ge=0.0, default=0.0)
    dtc_count: int = Field(ge=0, default=0)


class TelemetryIngestResult(BaseModel):
    """Response shape for single / batch ingest endpoints."""

    accepted: int = Field(..., description="Events successfully inserted")
    rejected: int = Field(
        default=0, description="Events rejected at the repository layer"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues (e.g. odometer regression)",
    )
