-- ============================================================================
-- Migration: 20260401000002_create_vehicles
-- Description: Create vehicles table with indexes for search/filtering
-- ============================================================================

CREATE TABLE public.vehicles (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  source_site           text        NOT NULL,
  source_url            text,
  source_id             text,
  category_id           uuid        NOT NULL REFERENCES public.vehicle_categories(id),
  manufacturer_id       uuid        NOT NULL REFERENCES public.manufacturers(id),
  body_type_id          uuid        REFERENCES public.body_types(id),
  model_name            text        NOT NULL,
  model_year            int,
  mileage_km            int,
  price_yen             bigint,
  price_tax_included    boolean     NOT NULL DEFAULT false,
  tonnage               numeric(6,2),
  engine_displacement_cc int,
  transmission          text,
  fuel_type             text,
  location_prefecture   text,
  image_url             text,
  scraped_at            timestamptz NOT NULL DEFAULT now(),
  is_active             boolean     NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.vehicles IS 'Scraped commercial vehicle listings from external sites';

-- Unique constraint: one record per source listing
ALTER TABLE public.vehicles
  ADD CONSTRAINT uq_vehicles_source UNIQUE (source_site, source_id);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_vehicles_category_id      ON public.vehicles (category_id);
CREATE INDEX idx_vehicles_manufacturer_id  ON public.vehicles (manufacturer_id);
CREATE INDEX idx_vehicles_body_type_id     ON public.vehicles (body_type_id);
CREATE INDEX idx_vehicles_model_year       ON public.vehicles (model_year);
CREATE INDEX idx_vehicles_price_yen        ON public.vehicles (price_yen);
CREATE INDEX idx_vehicles_scraped_at       ON public.vehicles (scraped_at DESC);

-- Composite index for common search pattern
CREATE INDEX idx_vehicles_search_composite
  ON public.vehicles (category_id, manufacturer_id, body_type_id, model_year, price_yen)
  WHERE is_active = true;

-- Trigger
CREATE TRIGGER trg_vehicles_updated_at
  BEFORE UPDATE ON public.vehicles
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
