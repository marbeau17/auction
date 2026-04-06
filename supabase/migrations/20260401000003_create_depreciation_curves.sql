-- ============================================================================
-- Migration: 20260401000003_create_depreciation_curves
-- Description: Create depreciation_curves table for residual value modeling
-- ============================================================================

CREATE TABLE public.depreciation_curves (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id       uuid        NOT NULL REFERENCES public.vehicle_categories(id),
  manufacturer_id   uuid        REFERENCES public.manufacturers(id),
  body_type_id      uuid        REFERENCES public.body_types(id),
  curve_type        text        NOT NULL DEFAULT 'linear'
                                CHECK (curve_type IN ('linear', 'declining_balance', 'custom')),
  useful_life_years int         NOT NULL,
  residual_rate     numeric(5,4) NOT NULL DEFAULT 0.1000
                                CHECK (residual_rate >= 0 AND residual_rate <= 1),
  custom_curve_json jsonb,
  effective_from    date        NOT NULL DEFAULT CURRENT_DATE,
  effective_to      date,
  notes             text,
  created_by        uuid        REFERENCES public.users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),

  -- effective_to must be after effective_from when set
  CONSTRAINT chk_depreciation_date_range
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);

COMMENT ON TABLE public.depreciation_curves
  IS 'Depreciation curve definitions used for residual value and leaseback pricing';
COMMENT ON COLUMN public.depreciation_curves.residual_rate
  IS 'Residual value as a fraction of original price (0.0 - 1.0)';
COMMENT ON COLUMN public.depreciation_curves.custom_curve_json
  IS 'Year-by-year rate overrides when curve_type = custom, e.g. [{"year":1,"rate":0.80},...]';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_depreciation_curves_category   ON public.depreciation_curves (category_id);
CREATE INDEX idx_depreciation_curves_effective   ON public.depreciation_curves (effective_from, effective_to);

-- Trigger
CREATE TRIGGER trg_depreciation_curves_updated_at
  BEFORE UPDATE ON public.depreciation_curves
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
