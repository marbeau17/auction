-- ============================================================================
-- Migration: 20260417000008_esg_scores
-- Description: ESG / transition-finance scoring tables (Phase-3c).
--              Stores per-vehicle CO2 intensity scores and per-fund fleet
--              snapshots used by green-bond / transition-finance reporting.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- vehicles.fuel_type column (idempotent)
-- ---------------------------------------------------------------------------
ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS fuel_type TEXT;

-- Drop and recreate the CHECK so migration is re-runnable
ALTER TABLE public.vehicles
  DROP CONSTRAINT IF EXISTS chk_vehicles_fuel_type;

ALTER TABLE public.vehicles
  ADD CONSTRAINT chk_vehicles_fuel_type
  CHECK (
    fuel_type IS NULL
    OR fuel_type IN ('diesel','gasoline','hybrid','ev','cng','lpg','other')
  );

COMMENT ON COLUMN public.vehicles.fuel_type IS
  'Fuel-type classification for ESG / transition-finance scoring';

-- ---------------------------------------------------------------------------
-- Table: esg_vehicle_scores — per-vehicle ESG / CO2 score history
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.esg_vehicle_scores (
  id                     uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id             uuid         NOT NULL REFERENCES public.vehicles(id) ON DELETE CASCADE,
  scored_at              timestamptz  NOT NULL DEFAULT now(),
  co2_intensity_g_km     numeric(10,2) NOT NULL CHECK (co2_intensity_g_km >= 0),
  grade                  char(1)      NOT NULL CHECK (grade IN ('A','B','C','D','E')),
  transition_eligible    boolean      NOT NULL DEFAULT false,
  payload                jsonb        NOT NULL DEFAULT '{}'::jsonb,
  created_at             timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.esg_vehicle_scores IS
  'Per-vehicle ESG score history (CO2 intensity, grade, transition-finance eligibility).';
COMMENT ON COLUMN public.esg_vehicle_scores.co2_intensity_g_km IS
  'Estimated CO2 emissions per km driven (grams).';
COMMENT ON COLUMN public.esg_vehicle_scores.grade IS
  'Letter grade A (best) through E (worst).';
COMMENT ON COLUMN public.esg_vehicle_scores.transition_eligible IS
  'True if the vehicle qualifies for transition-finance / green-bond eligibility.';
COMMENT ON COLUMN public.esg_vehicle_scores.payload IS
  'Full scoring payload (fuel_type, fuel_liters, methodology_note, etc.).';

CREATE INDEX IF NOT EXISTS idx_esg_vehicle_scores_vehicle_scored
  ON public.esg_vehicle_scores (vehicle_id, scored_at DESC);

CREATE INDEX IF NOT EXISTS idx_esg_vehicle_scores_scored_at
  ON public.esg_vehicle_scores (scored_at DESC);


-- ---------------------------------------------------------------------------
-- Table: esg_fleet_snapshots — per-fund daily fleet ESG aggregate
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.esg_fleet_snapshots (
  id                     uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id                uuid         NOT NULL REFERENCES public.funds(id) ON DELETE CASCADE,
  as_of_date             date         NOT NULL,
  avg_co2_intensity      numeric(10,2) NOT NULL DEFAULT 0 CHECK (avg_co2_intensity >= 0),
  total_tco2_year        numeric(14,3) NOT NULL DEFAULT 0 CHECK (total_tco2_year >= 0),
  transition_pct         numeric(6,2)  NOT NULL DEFAULT 0 CHECK (transition_pct >= 0 AND transition_pct <= 100),
  vehicles_count         integer      NOT NULL DEFAULT 0 CHECK (vehicles_count >= 0),
  payload                jsonb        NOT NULL DEFAULT '{}'::jsonb,
  created_at             timestamptz  NOT NULL DEFAULT now(),

  CONSTRAINT uq_esg_fleet_snapshots_fund_date UNIQUE (fund_id, as_of_date)
);

COMMENT ON TABLE public.esg_fleet_snapshots IS
  'Per-fund fleet ESG snapshot (one row per fund per day). Used for green-bond eligibility reporting.';
COMMENT ON COLUMN public.esg_fleet_snapshots.avg_co2_intensity IS
  'Weighted-average fleet CO2 intensity (g/km) on this date.';
COMMENT ON COLUMN public.esg_fleet_snapshots.total_tco2_year IS
  'Estimated total fleet CO2 emissions, annualized (tonnes/year).';
COMMENT ON COLUMN public.esg_fleet_snapshots.transition_pct IS
  '% of fleet eligible for transition finance.';
COMMENT ON COLUMN public.esg_fleet_snapshots.payload IS
  'Full snapshot payload including per-vehicle breakdown and weighted-average grade.';

CREATE INDEX IF NOT EXISTS idx_esg_fleet_snapshots_fund_id
  ON public.esg_fleet_snapshots (fund_id);

CREATE INDEX IF NOT EXISTS idx_esg_fleet_snapshots_as_of_date
  ON public.esg_fleet_snapshots (as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_esg_fleet_snapshots_fund_date
  ON public.esg_fleet_snapshots (fund_id, as_of_date DESC);


-- ============================================================================
-- Row Level Security
-- ============================================================================

-- esg_vehicle_scores --------------------------------------------------------
ALTER TABLE public.esg_vehicle_scores ENABLE ROW LEVEL SECURITY;

-- SELECT: admin + investor + asset_manager
DROP POLICY IF EXISTS esg_vehicle_scores_select ON public.esg_vehicle_scores;
CREATE POLICY esg_vehicle_scores_select ON public.esg_vehicle_scores
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'investor', 'asset_manager')
  );

-- INSERT: admin + service_role
DROP POLICY IF EXISTS esg_vehicle_scores_insert ON public.esg_vehicle_scores;
CREATE POLICY esg_vehicle_scores_insert ON public.esg_vehicle_scores
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );

-- UPDATE: admin only (historical record — normally append-only)
DROP POLICY IF EXISTS esg_vehicle_scores_update ON public.esg_vehicle_scores;
CREATE POLICY esg_vehicle_scores_update ON public.esg_vehicle_scores
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

-- DELETE: admin only
DROP POLICY IF EXISTS esg_vehicle_scores_delete ON public.esg_vehicle_scores;
CREATE POLICY esg_vehicle_scores_delete ON public.esg_vehicle_scores
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );


-- esg_fleet_snapshots -------------------------------------------------------
ALTER TABLE public.esg_fleet_snapshots ENABLE ROW LEVEL SECURITY;

-- SELECT: admin + investor + asset_manager
DROP POLICY IF EXISTS esg_fleet_snapshots_select ON public.esg_fleet_snapshots;
CREATE POLICY esg_fleet_snapshots_select ON public.esg_fleet_snapshots
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'investor', 'asset_manager')
  );

-- INSERT: admin + service_role
DROP POLICY IF EXISTS esg_fleet_snapshots_insert ON public.esg_fleet_snapshots;
CREATE POLICY esg_fleet_snapshots_insert ON public.esg_fleet_snapshots
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );

-- UPDATE: admin + service_role (for upserts of the same-day snapshot)
DROP POLICY IF EXISTS esg_fleet_snapshots_update ON public.esg_fleet_snapshots;
CREATE POLICY esg_fleet_snapshots_update ON public.esg_fleet_snapshots
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );

-- DELETE: admin only
DROP POLICY IF EXISTS esg_fleet_snapshots_delete ON public.esg_fleet_snapshots;
CREATE POLICY esg_fleet_snapshots_delete ON public.esg_fleet_snapshots
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );
