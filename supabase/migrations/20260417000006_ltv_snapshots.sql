-- ============================================================================
-- Migration: 20260417000006_ltv_snapshots
-- Description: Fund-level LTV (Loan-to-Value) snapshot history.
--              Stores covenant-tracking LTV ratios and collateral headroom
--              per fund per date so we can plot trends, detect breaches,
--              and replay stress-test inputs.
--
-- Related: docs/ltv_valuation_spec.md §4.3
-- Covenant thresholds (application-side defaults):
--   * WARNING ≥ 0.75
--   * BREACH  ≥ 0.85
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: ltv_snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE public.ltv_snapshots (
  id                          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id                     uuid         NOT NULL REFERENCES public.funds(id) ON DELETE CASCADE,
  as_of_date                  date         NOT NULL,
  ltv_ratio                   numeric(6,4) NOT NULL CHECK (ltv_ratio >= 0),
  book_value_total            bigint       NOT NULL CHECK (book_value_total >= 0),
  outstanding_principal_total bigint       NOT NULL CHECK (outstanding_principal_total >= 0),
  vehicles_count              integer      NOT NULL DEFAULT 0 CHECK (vehicles_count >= 0),
  breach_count                integer      NOT NULL DEFAULT 0 CHECK (breach_count >= 0),
  payload                     jsonb        NOT NULL DEFAULT '{}'::jsonb,
  created_at                  timestamptz  NOT NULL DEFAULT now(),

  CONSTRAINT uq_ltv_snapshot_fund_date UNIQUE (fund_id, as_of_date)
);

COMMENT ON TABLE  public.ltv_snapshots                              IS 'Fund-level LTV (outstanding principal / book value) snapshot history for covenant monitoring';
COMMENT ON COLUMN public.ltv_snapshots.as_of_date                    IS 'Valuation date (typically month-end; can be ad-hoc)';
COMMENT ON COLUMN public.ltv_snapshots.ltv_ratio                     IS 'Aggregate outstanding_principal_total / book_value_total as decimal (e.g. 0.7500 = 75%)';
COMMENT ON COLUMN public.ltv_snapshots.book_value_total              IS 'Σ book_value across all vehicles in the fund (JPY)';
COMMENT ON COLUMN public.ltv_snapshots.outstanding_principal_total   IS 'Σ remaining unpaid lease principal across all vehicles in the fund (JPY)';
COMMENT ON COLUMN public.ltv_snapshots.vehicles_count                IS 'Number of vehicles included in this snapshot';
COMMENT ON COLUMN public.ltv_snapshots.breach_count                  IS 'Number of vehicles whose individual LTV crossed the breach threshold (default 0.85)';
COMMENT ON COLUMN public.ltv_snapshots.payload                       IS 'Full LTVFundResult JSON including per-vehicle breakdown and thresholds';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_ltv_snapshots_fund_date
  ON public.ltv_snapshots (fund_id, as_of_date DESC);

CREATE INDEX idx_ltv_snapshots_as_of_date
  ON public.ltv_snapshots (as_of_date DESC);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
ALTER TABLE public.ltv_snapshots ENABLE ROW LEVEL SECURITY;

-- SELECT: admin + operator (fleet-wide) + investor (restricted to own fund)
--
-- Investors are allowlisted globally here; per-fund investor scoping is
-- additionally enforced at the API layer using the require_permission(
-- "fund_info", "read") guard and the stakeholder-fund mapping.  This
-- matches the pattern already used for vehicle_nav_history / fund_metrics.
CREATE POLICY ltv_snapshots_select ON public.ltv_snapshots
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'operator', 'investor', 'asset_manager')
  );

-- INSERT: admin + service_role (scheduler / batch workflow)
CREATE POLICY ltv_snapshots_insert ON public.ltv_snapshots
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );

-- UPDATE: admin + service_role (upsert requires UPDATE permission too)
CREATE POLICY ltv_snapshots_update ON public.ltv_snapshots
  FOR UPDATE USING (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );

-- DELETE: admin only (cleanup)
CREATE POLICY ltv_snapshots_delete ON public.ltv_snapshots
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );
