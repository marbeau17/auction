-- ============================================================================
-- Migration: 20260401000001_create_master_tables
-- Description: Create vehicle_categories, manufacturers, body_types
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: vehicle_categories
-- ---------------------------------------------------------------------------
CREATE TABLE public.vehicle_categories (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text        NOT NULL,
  code          text        UNIQUE NOT NULL,
  display_order int         NOT NULL DEFAULT 0,
  is_active     boolean     NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.vehicle_categories IS 'Master: vehicle size/type categories (large truck, trailer, etc.)';

CREATE TRIGGER trg_vehicle_categories_updated_at
  BEFORE UPDATE ON public.vehicle_categories
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: manufacturers
-- ---------------------------------------------------------------------------
CREATE TABLE public.manufacturers (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text        NOT NULL,
  name_en       text,
  code          text        UNIQUE NOT NULL,
  country       text        NOT NULL DEFAULT 'JP',
  display_order int         NOT NULL DEFAULT 0,
  is_active     boolean     NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.manufacturers IS 'Master: vehicle manufacturers';

CREATE TRIGGER trg_manufacturers_updated_at
  BEFORE UPDATE ON public.manufacturers
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: body_types
-- ---------------------------------------------------------------------------
CREATE TABLE public.body_types (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text        NOT NULL,
  code          text        UNIQUE NOT NULL,
  category_id   uuid        REFERENCES public.vehicle_categories(id) ON DELETE SET NULL,
  display_order int         NOT NULL DEFAULT 0,
  is_active     boolean     NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.body_types IS 'Master: vehicle body types (wing, van, flat, etc.)';

CREATE INDEX idx_body_types_category_id ON public.body_types (category_id);

CREATE TRIGGER trg_body_types_updated_at
  BEFORE UPDATE ON public.body_types
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
