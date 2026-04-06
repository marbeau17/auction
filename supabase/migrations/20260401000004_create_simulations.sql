-- ============================================================================
-- Migration: 20260401000004_create_simulations
-- Description: Create simulations and simulation_params tables
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: simulations
-- ---------------------------------------------------------------------------
CREATE TABLE public.simulations (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               uuid        NOT NULL REFERENCES public.users(id),
  title                 text,
  category_id           uuid        REFERENCES public.vehicle_categories(id),
  manufacturer_id       uuid        REFERENCES public.manufacturers(id),
  body_type_id          uuid        REFERENCES public.body_types(id),
  target_model_name     text,
  target_model_year     int,
  target_mileage_km     int,
  market_price_yen      bigint,
  purchase_price_yen    bigint,
  lease_monthly_yen     bigint,
  lease_term_months     int,
  total_lease_revenue_yen bigint,
  expected_yield_rate   numeric(6,4),
  result_summary_json   jsonb,
  status                text        NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft', 'completed', 'submitted', 'approved')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.simulations IS 'Leaseback pricing simulation records';
COMMENT ON COLUMN public.simulations.expected_yield_rate IS 'Expected annual yield as decimal (e.g. 0.0850 = 8.5%)';

-- Indexes
CREATE INDEX idx_simulations_user_id     ON public.simulations (user_id);
CREATE INDEX idx_simulations_status      ON public.simulations (status);
CREATE INDEX idx_simulations_created_at  ON public.simulations (created_at DESC);
CREATE INDEX idx_simulations_category    ON public.simulations (category_id);

-- Trigger
CREATE TRIGGER trg_simulations_updated_at
  BEFORE UPDATE ON public.simulations
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: simulation_params
-- ---------------------------------------------------------------------------
CREATE TABLE public.simulation_params (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  simulation_id   uuid        NOT NULL REFERENCES public.simulations(id) ON DELETE CASCADE,
  param_key       text        NOT NULL,
  param_value     numeric(18,6),
  param_unit      text,
  description     text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_simulation_params_key UNIQUE (simulation_id, param_key)
);

COMMENT ON TABLE public.simulation_params IS 'Key-value parameters for each simulation run';

-- Indexes
CREATE INDEX idx_simulation_params_simulation_id ON public.simulation_params (simulation_id);

-- Trigger
CREATE TRIGGER trg_simulation_params_updated_at
  BEFORE UPDATE ON public.simulation_params
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
