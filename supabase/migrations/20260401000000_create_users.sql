-- ============================================================================
-- Migration: 20260401000000_create_users
-- Description: Create users table and updated_at trigger function
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Function: update updated_at column automatically on row modification
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.set_updated_at()
  IS 'Trigger function to auto-set updated_at on row update';

-- ---------------------------------------------------------------------------
-- Table: users
-- ---------------------------------------------------------------------------
CREATE TABLE public.users (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  email           text        UNIQUE NOT NULL,
  full_name       text        NOT NULL,
  role            text        NOT NULL DEFAULT 'sales'
                              CHECK (role IN ('admin', 'sales', 'viewer')),
  department      text,
  is_active       boolean     NOT NULL DEFAULT true,
  last_signed_in_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.users IS 'Application users with role-based access';
COMMENT ON COLUMN public.users.role IS 'admin: full access, sales: simulations, viewer: read-only';

-- Trigger: auto-update updated_at
CREATE TRIGGER trg_users_updated_at
  BEFORE UPDATE ON public.users
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
