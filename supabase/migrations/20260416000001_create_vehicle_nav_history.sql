-- ============================================================================
-- Migration: 20260416000001_create_vehicle_nav_history
-- Description: Create vehicle NAV (Net Asset Value) history tracking table
--              for monthly valuation snapshots per vehicle
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: vehicle_nav_history
-- ---------------------------------------------------------------------------
CREATE TABLE public.vehicle_nav_history (
  id                        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id                uuid        NOT NULL REFERENCES public.vehicles(id) ON DELETE CASCADE,
  fund_id                   uuid        REFERENCES public.funds(id),
  sab_id                    uuid        REFERENCES public.secured_asset_blocks(id),
  recording_date            date        NOT NULL,
  acquisition_price         bigint      NOT NULL CHECK (acquisition_price > 0),
  book_value                bigint      NOT NULL CHECK (book_value >= 0),
  market_value              bigint      CHECK (market_value >= 0),
  depreciation_cumulative   bigint      NOT NULL DEFAULT 0 CHECK (depreciation_cumulative >= 0),
  lease_income_cumulative   bigint      NOT NULL DEFAULT 0 CHECK (lease_income_cumulative >= 0),
  nav                       bigint      NOT NULL,
  ltv_ratio                 numeric(6,4) CHECK (ltv_ratio >= 0),
  notes                     text,
  created_at                timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_vehicle_nav_date UNIQUE (vehicle_id, recording_date)
);

COMMENT ON TABLE public.vehicle_nav_history IS 'Monthly NAV snapshots per vehicle — tracks book value, market value, depreciation, and lease income over time';
COMMENT ON COLUMN public.vehicle_nav_history.recording_date IS 'Snapshot date (typically month-end)';
COMMENT ON COLUMN public.vehicle_nav_history.acquisition_price IS 'Original acquisition price in JPY';
COMMENT ON COLUMN public.vehicle_nav_history.book_value IS 'Current book value after depreciation in JPY';
COMMENT ON COLUMN public.vehicle_nav_history.market_value IS 'Current estimated market value in JPY (auction/wholesale)';
COMMENT ON COLUMN public.vehicle_nav_history.depreciation_cumulative IS 'Cumulative depreciation from acquisition date in JPY';
COMMENT ON COLUMN public.vehicle_nav_history.lease_income_cumulative IS 'Cumulative lease income earned from this vehicle in JPY';
COMMENT ON COLUMN public.vehicle_nav_history.nav IS 'Net Asset Value = book_value + lease_income_cumulative - depreciation adjustments';
COMMENT ON COLUMN public.vehicle_nav_history.ltv_ratio IS 'Loan-to-Value ratio as decimal (e.g. 0.7500 = 75%)';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_vehicle_nav_history_vehicle_id
  ON public.vehicle_nav_history (vehicle_id);

CREATE INDEX idx_vehicle_nav_history_fund_id
  ON public.vehicle_nav_history (fund_id);

CREATE INDEX idx_vehicle_nav_history_sab_id
  ON public.vehicle_nav_history (sab_id);

CREATE INDEX idx_vehicle_nav_history_recording_date
  ON public.vehicle_nav_history (recording_date DESC);

-- Composite index for fund-level monthly queries
CREATE INDEX idx_vehicle_nav_history_fund_date
  ON public.vehicle_nav_history (fund_id, recording_date DESC);

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
ALTER TABLE public.vehicle_nav_history ENABLE ROW LEVEL SECURITY;

-- All authenticated users can read NAV history
CREATE POLICY vehicle_nav_history_select ON public.vehicle_nav_history
  FOR SELECT USING (true);

-- Only admins and service_role can insert
CREATE POLICY vehicle_nav_history_insert ON public.vehicle_nav_history
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );

-- Only admins can update (corrections)
CREATE POLICY vehicle_nav_history_update ON public.vehicle_nav_history
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

-- Only admins can delete (cleanup)
CREATE POLICY vehicle_nav_history_delete ON public.vehicle_nav_history
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );
