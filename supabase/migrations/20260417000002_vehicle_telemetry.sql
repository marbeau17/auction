-- ============================================================================
-- Migration: 20260417000002_vehicle_telemetry
-- Description: Phase-3a telemetry ingestion foundation.
--              Creates raw `vehicle_telemetry` event table and
--              `telemetry_aggregates` daily rollup table.
-- Reference : docs/telemetry_roadmap.md (Phase 3a)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: vehicle_telemetry
--   Raw, per-event telemetry payload received from OBD-II / telematics
--   devices (Webhook or MQTT bridge). Retention target: 30 days (enforced by
--   a separate job; not schema-level).
-- ---------------------------------------------------------------------------
CREATE TABLE public.vehicle_telemetry (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id        uuid        NOT NULL REFERENCES public.vehicles(id) ON DELETE CASCADE,
  device_id         text        NOT NULL,
  recorded_at       timestamptz NOT NULL,
  odometer_km       integer     CHECK (odometer_km IS NULL OR odometer_km >= 0),
  fuel_level_pct    numeric(5,2) CHECK (fuel_level_pct IS NULL OR (fuel_level_pct >= 0 AND fuel_level_pct <= 100)),
  engine_hours      numeric(10,2) CHECK (engine_hours IS NULL OR engine_hours >= 0),
  location_geojson  jsonb,
  dtc_codes         text[]      NOT NULL DEFAULT ARRAY[]::text[],
  raw_payload       jsonb,
  created_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.vehicle_telemetry IS 'Raw per-event telemetry from OBD-II / telematics devices (Phase 3a foundation)';
COMMENT ON COLUMN public.vehicle_telemetry.device_id        IS 'Vendor device identifier (e.g. DEV-20260101-0001)';
COMMENT ON COLUMN public.vehicle_telemetry.recorded_at      IS 'Device-side timestamp of the sample';
COMMENT ON COLUMN public.vehicle_telemetry.odometer_km      IS 'Cumulative odometer reading in km';
COMMENT ON COLUMN public.vehicle_telemetry.fuel_level_pct   IS 'Fuel tank level as a percentage (0-100)';
COMMENT ON COLUMN public.vehicle_telemetry.engine_hours     IS 'Cumulative engine operating hours';
COMMENT ON COLUMN public.vehicle_telemetry.location_geojson IS 'GeoJSON Point: {"type":"Point","coordinates":[lng,lat]}';
COMMENT ON COLUMN public.vehicle_telemetry.dtc_codes        IS 'Active Diagnostic Trouble Codes (uppercase)';
COMMENT ON COLUMN public.vehicle_telemetry.raw_payload      IS 'Full vendor payload for audit / schema evolution';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_vehicle_telemetry_vehicle_recorded
  ON public.vehicle_telemetry (vehicle_id, recorded_at DESC);

CREATE INDEX idx_vehicle_telemetry_device_recorded
  ON public.vehicle_telemetry (device_id, recorded_at DESC);

-- ---------------------------------------------------------------------------
-- Table: telemetry_aggregates
--   Pre-computed daily rollups per vehicle. Written by a (future) rollup
--   job; this foundation provides the schema and read APIs only.
-- ---------------------------------------------------------------------------
CREATE TABLE public.telemetry_aggregates (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id            uuid        NOT NULL REFERENCES public.vehicles(id) ON DELETE CASCADE,
  agg_date              date        NOT NULL,
  km_driven             integer     NOT NULL DEFAULT 0 CHECK (km_driven >= 0),
  avg_fuel_pct          numeric(5,2) CHECK (avg_fuel_pct IS NULL OR (avg_fuel_pct >= 0 AND avg_fuel_pct <= 100)),
  engine_hours_delta    numeric(10,2) NOT NULL DEFAULT 0 CHECK (engine_hours_delta >= 0),
  dtc_count             integer     NOT NULL DEFAULT 0 CHECK (dtc_count >= 0),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_telemetry_aggregates_vehicle_date UNIQUE (vehicle_id, agg_date)
);

COMMENT ON TABLE  public.telemetry_aggregates IS 'Daily telemetry rollups per vehicle (km driven, avg fuel, engine-hours delta, DTC count)';
COMMENT ON COLUMN public.telemetry_aggregates.km_driven          IS 'Kilometres driven that day (odometer_max - odometer_min)';
COMMENT ON COLUMN public.telemetry_aggregates.avg_fuel_pct       IS 'Arithmetic mean of fuel_level_pct samples that day';
COMMENT ON COLUMN public.telemetry_aggregates.engine_hours_delta IS 'Engine hours accumulated that day';
COMMENT ON COLUMN public.telemetry_aggregates.dtc_count          IS 'Distinct DTC codes observed that day';

CREATE INDEX idx_telemetry_aggregates_vehicle_date
  ON public.telemetry_aggregates (vehicle_id, agg_date DESC);

CREATE TRIGGER trg_telemetry_aggregates_updated_at
  BEFORE UPDATE ON public.telemetry_aggregates
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ============================================================================
-- Row Level Security
--   SELECT: fleet owner (vehicle.fund_id -> fund membership), admin, AM
--   INSERT: service_role only (ingest worker / REST ingest endpoint)
-- ============================================================================
ALTER TABLE public.vehicle_telemetry     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.telemetry_aggregates  ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- vehicle_telemetry policies
-- ---------------------------------------------------------------------------
CREATE POLICY vehicle_telemetry_select ON public.vehicle_telemetry
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'asset_manager')
    OR EXISTS (
      SELECT 1
      FROM public.vehicles v
      LEFT JOIN public.funds f ON f.id = v.fund_id
      WHERE v.id = vehicle_telemetry.vehicle_id
        AND (
          public.current_user_role() = 'admin'
          OR f.owner_id = auth.uid()
        )
    )
  );

CREATE POLICY vehicle_telemetry_insert ON public.vehicle_telemetry
  FOR INSERT WITH CHECK (
    auth.role() = 'service_role'
  );

-- ---------------------------------------------------------------------------
-- telemetry_aggregates policies
-- ---------------------------------------------------------------------------
CREATE POLICY telemetry_aggregates_select ON public.telemetry_aggregates
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'asset_manager')
    OR EXISTS (
      SELECT 1
      FROM public.vehicles v
      LEFT JOIN public.funds f ON f.id = v.fund_id
      WHERE v.id = telemetry_aggregates.vehicle_id
        AND (
          public.current_user_role() = 'admin'
          OR f.owner_id = auth.uid()
        )
    )
  );

CREATE POLICY telemetry_aggregates_insert ON public.telemetry_aggregates
  FOR INSERT WITH CHECK (
    auth.role() = 'service_role'
  );
