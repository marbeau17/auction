-- ============================================================================
-- Migration: 20260417000003_liquidation
-- Description: Phase-2C Global Liquidation foundation.
--              Creates liquidation_cases (state machine) and liquidation_events
--              (append-only audit log) for NLV routing between domestic resale,
--              export, auction, and scrap channels.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: liquidation_cases
-- ---------------------------------------------------------------------------
CREATE TABLE public.liquidation_cases (
  id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id           uuid        NOT NULL REFERENCES public.vehicles(id) ON DELETE RESTRICT,
  sab_id               uuid        REFERENCES public.secured_asset_blocks(id),
  fund_id              uuid        REFERENCES public.funds(id),
  triggered_by         text        NOT NULL
                                    CHECK (triggered_by IN ('default', 'maturity', 'voluntary')),
  status               text        NOT NULL DEFAULT 'assessing'
                                    CHECK (status IN ('assessing', 'routing', 'listed', 'sold', 'closed', 'cancelled')),
  detected_at          timestamptz NOT NULL DEFAULT now(),
  assessed_by          uuid        REFERENCES public.users(id),
  assessment_deadline  date        NOT NULL,   -- T+10 days from detected_at
  closure_deadline     date        NOT NULL,   -- T+31..T+74 based on chosen route
  route                text        CHECK (route IN ('domestic_resale', 'export', 'auction', 'scrap')),
  nlv_jpy              bigint,
  realized_price_jpy   bigint,
  cost_breakdown       jsonb       NOT NULL DEFAULT '{}'::jsonb,
  -- cost_breakdown keys: transport, customs, inspection, yard, commission
  notes                text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.liquidation_cases IS 'Liquidation case state machine: assessing -> routing -> listed -> sold -> closed (cancelled allowed from any state)';
COMMENT ON COLUMN public.liquidation_cases.triggered_by IS 'default=lessee default, maturity=lease expiry, voluntary=owner-initiated disposal';
COMMENT ON COLUMN public.liquidation_cases.assessment_deadline IS 'T+10: deadline to complete NLV assessment and commit a route';
COMMENT ON COLUMN public.liquidation_cases.closure_deadline IS 'Deadline to fully realise the sale (T+31 domestic / T+45 auction / T+74 export)';
COMMENT ON COLUMN public.liquidation_cases.route IS 'Committed disposal channel (nullable until routing decision)';
COMMENT ON COLUMN public.liquidation_cases.nlv_jpy IS 'Estimated Net Liquidation Value at routing commit (JPY)';
COMMENT ON COLUMN public.liquidation_cases.realized_price_jpy IS 'Actual realised sale proceeds at closure (JPY)';
COMMENT ON COLUMN public.liquidation_cases.cost_breakdown IS 'JSONB with keys transport, customs, inspection, yard, commission (JPY)';

-- ---------------------------------------------------------------------------
-- Indexes: liquidation_cases
-- ---------------------------------------------------------------------------
CREATE INDEX idx_liquidation_cases_status
  ON public.liquidation_cases (status);

CREATE INDEX idx_liquidation_cases_closure_deadline
  ON public.liquidation_cases (closure_deadline);

CREATE INDEX idx_liquidation_cases_fund_status
  ON public.liquidation_cases (fund_id, status);

CREATE INDEX idx_liquidation_cases_vehicle_id
  ON public.liquidation_cases (vehicle_id);

CREATE TRIGGER trg_liquidation_cases_updated_at
  BEFORE UPDATE ON public.liquidation_cases
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: liquidation_events (append-only audit log)
-- ---------------------------------------------------------------------------
CREATE TABLE public.liquidation_events (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id        uuid        NOT NULL REFERENCES public.liquidation_cases(id) ON DELETE CASCADE,
  event_type     text        NOT NULL,
  -- common event_types: case_created, nlv_estimated, route_committed,
  --                     listed, offer_received, sold, closed, cancelled, note
  payload        jsonb       NOT NULL DEFAULT '{}'::jsonb,
  actor_user_id  uuid        REFERENCES public.users(id),
  occurred_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.liquidation_events IS 'Append-only audit log of all state transitions and observations on a liquidation case';
COMMENT ON COLUMN public.liquidation_events.event_type IS 'Event category (e.g. case_created, nlv_estimated, route_committed, sold, closed)';
COMMENT ON COLUMN public.liquidation_events.payload IS 'Event-specific JSON payload (NLV estimates, route details, etc.)';

CREATE INDEX idx_liquidation_events_case_id
  ON public.liquidation_events (case_id, occurred_at DESC);

CREATE INDEX idx_liquidation_events_type
  ON public.liquidation_events (event_type);

-- ============================================================================
-- Row Level Security
-- ============================================================================
ALTER TABLE public.liquidation_cases  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.liquidation_events ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- Policies: liquidation_cases
-- SELECT: admin + operator + asset_manager
-- INSERT: admin + service_role (case creation is gated via API + RBAC)
-- UPDATE: admin + operator (state transitions)
-- DELETE: admin only
-- ---------------------------------------------------------------------------
CREATE POLICY liquidation_cases_select ON public.liquidation_cases
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'operator', 'asset_manager')
  );

CREATE POLICY liquidation_cases_insert ON public.liquidation_cases
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );

CREATE POLICY liquidation_cases_update ON public.liquidation_cases
  FOR UPDATE USING (
    public.current_user_role() IN ('admin', 'operator')
  );

CREATE POLICY liquidation_cases_delete ON public.liquidation_cases
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- ---------------------------------------------------------------------------
-- Policies: liquidation_events
-- SELECT: admin + operator + asset_manager
-- INSERT: admin + service_role (events are emitted via API)
-- No UPDATE / DELETE — events are append-only
-- ---------------------------------------------------------------------------
CREATE POLICY liquidation_events_select ON public.liquidation_events
  FOR SELECT USING (
    public.current_user_role() IN ('admin', 'operator', 'asset_manager')
  );

CREATE POLICY liquidation_events_insert ON public.liquidation_events
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin' OR auth.role() = 'service_role'
  );
