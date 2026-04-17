-- ============================================================================
-- Migration: 20260417000001_vehicle_inventory_columns
-- Description: Add Epic 4 vehicle inventory columns to public.vehicles
--              (fund ownership, NAV, acquisition, lease linkage) and plug
--              RLS gap on public.invoice_approvals (UPDATE + DELETE policies).
--
-- Notes:
--   * Uses `inventory_status` (not `status`) to avoid any clash with existing
--     vehicle lifecycle semantics — the base `vehicles` table uses `is_active`
--     today, but we reserve the unqualified `status` name for future use.
--   * All ADDs are IF NOT EXISTS so this migration is idempotent.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- vehicles: inventory columns
-- ---------------------------------------------------------------------------
ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS current_nav              bigint;

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS inventory_status         text
    CHECK (inventory_status IN ('held', 'leased', 'disposing', 'disposed'));

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS residual_value_setting   bigint;

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS acquisition_price        bigint;

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS acquisition_date         date;

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS lease_contract_id        uuid
    REFERENCES public.lease_contracts(id);

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS fund_id                  uuid
    REFERENCES public.funds(id);

ALTER TABLE public.vehicles
  ADD COLUMN IF NOT EXISTS sab_id                   uuid
    REFERENCES public.secured_asset_blocks(id);

COMMENT ON COLUMN public.vehicles.current_nav             IS 'Latest Net Asset Value (JPY); kept in sync from vehicle_nav_history';
COMMENT ON COLUMN public.vehicles.inventory_status        IS 'Fund-inventory lifecycle: held / leased / disposing / disposed';
COMMENT ON COLUMN public.vehicles.residual_value_setting  IS 'Residual value (JPY) used as input to lease pricing';
COMMENT ON COLUMN public.vehicles.acquisition_price       IS 'Fund acquisition price (JPY)';
COMMENT ON COLUMN public.vehicles.acquisition_date        IS 'Date the fund acquired this vehicle';
COMMENT ON COLUMN public.vehicles.lease_contract_id       IS 'Active lease contract (when inventory_status = leased)';
COMMENT ON COLUMN public.vehicles.fund_id                 IS 'Owning fund';
COMMENT ON COLUMN public.vehicles.sab_id                  IS 'Secured Asset Block allocation';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_vehicles_fund_id
  ON public.vehicles (fund_id);

CREATE INDEX IF NOT EXISTS idx_vehicles_sab_id
  ON public.vehicles (sab_id);

CREATE INDEX IF NOT EXISTS idx_vehicles_lease_contract_id
  ON public.vehicles (lease_contract_id);

CREATE INDEX IF NOT EXISTS idx_vehicles_inventory_status
  ON public.vehicles (inventory_status);

-- Composite index for fund-scoped inventory queries
CREATE INDEX IF NOT EXISTS idx_vehicles_fund_inventory_status
  ON public.vehicles (fund_id, inventory_status);

-- ============================================================================
-- RLS gap fix: invoice_approvals needed UPDATE + DELETE policies (admin only).
-- The original migration (20260410000002_create_invoice_tables.sql) only
-- defined SELECT + INSERT, which silently blocks any corrections / cleanups
-- once RLS is enabled. Mirror the admin_check expression used for
-- invoices_update / invoices_delete: public.current_user_role() = 'admin'.
-- ============================================================================

CREATE POLICY invoice_approvals_admin_update ON public.invoice_approvals
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY invoice_approvals_admin_delete ON public.invoice_approvals
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );
