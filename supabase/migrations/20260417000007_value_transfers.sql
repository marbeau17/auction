-- ============================================================================
-- Migration: 20260417000007_value_transfers
-- Description: Phase-2 Value Transfer Engine persistence layer.
--              Stores computed per-period value allocations (gross income,
--              net income, per-role breakdown, reconciliation diff) and the
--              corresponding transfer instruction plan — money is NEVER
--              actually moved here, the engine only produces a plan that
--              downstream treasury systems can execute.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: value_allocations
-- One row per (fund_id, period_start, period_end) computation.
-- ---------------------------------------------------------------------------
CREATE TABLE public.value_allocations (
  id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id                uuid        NOT NULL REFERENCES public.funds(id) ON DELETE RESTRICT,
  period_start           date        NOT NULL,
  period_end             date        NOT NULL,
  gross_income           bigint      NOT NULL DEFAULT 0 CHECK (gross_income >= 0),
  net_income             bigint      NOT NULL DEFAULT 0,
  allocation             jsonb       NOT NULL DEFAULT '{}'::jsonb,
  -- allocation keys:
  --   accounting_fee, operator_margin, placement_fee_amortized,
  --   am_fee, investor_dividend, residual_to_spc
  reconciliation_diff    bigint      NOT NULL DEFAULT 0,
  status                 text        NOT NULL DEFAULT 'draft'
                                       CHECK (status IN ('draft', 'approved', 'executed')),
  created_at             timestamptz NOT NULL DEFAULT now(),
  approved_at            timestamptz,
  approved_by            uuid        REFERENCES public.users(id),

  CONSTRAINT chk_value_allocations_period
    CHECK (period_end >= period_start)
);

COMMENT ON TABLE  public.value_allocations IS 'Per-period value allocation computed from realised invoice income. One row per (fund_id, period).';
COMMENT ON COLUMN public.value_allocations.gross_income IS 'Sum of invoice subtotals (tax-exclusive) for invoices with status in (paid, sent) within the period';
COMMENT ON COLUMN public.value_allocations.net_income IS 'Gross income minus all stakeholder fee deductions (what remains for the SPC)';
COMMENT ON COLUMN public.value_allocations.allocation IS 'JSONB breakdown of per-role amounts (accounting_fee, operator_margin, placement_fee_amortized, am_fee, investor_dividend, residual_to_spc)';
COMMENT ON COLUMN public.value_allocations.reconciliation_diff IS 'gross_income - sum(allocation values); should be 0 on a happy-path compute';
COMMENT ON COLUMN public.value_allocations.status IS 'draft=computed but not locked, approved=locked by admin, executed=downstream treasury has run the plan';

-- Indexes
CREATE INDEX idx_value_allocations_fund_period
  ON public.value_allocations (fund_id, period_start);

CREATE INDEX idx_value_allocations_status
  ON public.value_allocations (status);

-- ---------------------------------------------------------------------------
-- Table: transfer_instructions
-- One row per stakeholder leg of a value_allocation distribution plan.
-- ---------------------------------------------------------------------------
CREATE TABLE public.transfer_instructions (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  allocation_id    uuid        NOT NULL REFERENCES public.value_allocations(id) ON DELETE CASCADE,
  stakeholder_role text        NOT NULL,
  amount_jpy       bigint      NOT NULL CHECK (amount_jpy >= 0),
  memo             text,
  status           text        NOT NULL DEFAULT 'planned'
                                 CHECK (status IN ('planned', 'sent', 'failed')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  executed_at      timestamptz
);

COMMENT ON TABLE  public.transfer_instructions IS 'Per-stakeholder distribution leg of a value_allocation. Plan-only: money is moved by downstream treasury.';
COMMENT ON COLUMN public.transfer_instructions.stakeholder_role IS 'accountant | operator | placement_agent | asset_manager | investor | spc';
COMMENT ON COLUMN public.transfer_instructions.memo IS 'Free-form memo for the wire/ledger line';

-- Indexes
CREATE INDEX idx_transfer_instructions_allocation
  ON public.transfer_instructions (allocation_id);

CREATE INDEX idx_transfer_instructions_status
  ON public.transfer_instructions (status);

-- ============================================================================
-- Row Level Security
-- ============================================================================
ALTER TABLE public.value_allocations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transfer_instructions  ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- Policies: value_allocations
-- SELECT: admin + operator + asset_manager
-- INSERT: admin + service_role (created through API with RBAC)
-- UPDATE: admin only (approval / status promotion)
-- DELETE: admin only
-- ---------------------------------------------------------------------------
CREATE POLICY value_allocations_select ON public.value_allocations
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'operator', 'asset_manager')
  );

CREATE POLICY value_allocations_insert ON public.value_allocations
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );

CREATE POLICY value_allocations_update ON public.value_allocations
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY value_allocations_delete ON public.value_allocations
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- ---------------------------------------------------------------------------
-- Policies: transfer_instructions
-- SELECT: admin + operator + asset_manager
-- INSERT: admin + service_role
-- UPDATE: admin only (mark sent / failed)
-- DELETE: admin only
-- ---------------------------------------------------------------------------
CREATE POLICY transfer_instructions_select ON public.transfer_instructions
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'operator', 'asset_manager')
  );

CREATE POLICY transfer_instructions_insert ON public.transfer_instructions
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );

CREATE POLICY transfer_instructions_update ON public.transfer_instructions
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY transfer_instructions_delete ON public.transfer_instructions
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );
