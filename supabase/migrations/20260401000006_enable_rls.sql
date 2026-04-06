-- ============================================================================
-- Migration: 20260401000006_enable_rls
-- Description: Enable Row Level Security and create access policies
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Helper: get current user's role from the users table
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.current_user_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
  SELECT role FROM public.users WHERE id = auth.uid();
$$;

-- ============================================================================
-- Enable RLS on all tables
-- ============================================================================
ALTER TABLE public.users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vehicle_categories   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.manufacturers        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.body_types           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vehicles             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.depreciation_curves  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.simulations          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.simulation_params    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scraping_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vehicle_price_history ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Policies: users
-- Users can read their own row; admins can read all
-- ============================================================================
CREATE POLICY users_select_own ON public.users
  FOR SELECT USING (
    id = auth.uid() OR public.current_user_role() = 'admin'
  );

CREATE POLICY users_update_own ON public.users
  FOR UPDATE USING (
    id = auth.uid() OR public.current_user_role() = 'admin'
  );

CREATE POLICY users_insert_admin ON public.users
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
  );

CREATE POLICY users_delete_admin ON public.users
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- ============================================================================
-- Policies: master tables (vehicle_categories, manufacturers, body_types)
-- All authenticated users can read; only admins can write
-- ============================================================================

-- vehicle_categories
CREATE POLICY vehicle_categories_select ON public.vehicle_categories
  FOR SELECT USING (true);

CREATE POLICY vehicle_categories_insert ON public.vehicle_categories
  FOR INSERT WITH CHECK (public.current_user_role() = 'admin');

CREATE POLICY vehicle_categories_update ON public.vehicle_categories
  FOR UPDATE USING (public.current_user_role() = 'admin');

CREATE POLICY vehicle_categories_delete ON public.vehicle_categories
  FOR DELETE USING (public.current_user_role() = 'admin');

-- manufacturers
CREATE POLICY manufacturers_select ON public.manufacturers
  FOR SELECT USING (true);

CREATE POLICY manufacturers_insert ON public.manufacturers
  FOR INSERT WITH CHECK (public.current_user_role() = 'admin');

CREATE POLICY manufacturers_update ON public.manufacturers
  FOR UPDATE USING (public.current_user_role() = 'admin');

CREATE POLICY manufacturers_delete ON public.manufacturers
  FOR DELETE USING (public.current_user_role() = 'admin');

-- body_types
CREATE POLICY body_types_select ON public.body_types
  FOR SELECT USING (true);

CREATE POLICY body_types_insert ON public.body_types
  FOR INSERT WITH CHECK (public.current_user_role() = 'admin');

CREATE POLICY body_types_update ON public.body_types
  FOR UPDATE USING (public.current_user_role() = 'admin');

CREATE POLICY body_types_delete ON public.body_types
  FOR DELETE USING (public.current_user_role() = 'admin');

-- ============================================================================
-- Policies: vehicles
-- All authenticated users can read; only service_role can write (scraper)
-- ============================================================================
CREATE POLICY vehicles_select ON public.vehicles
  FOR SELECT USING (true);

CREATE POLICY vehicles_insert_service ON public.vehicles
  FOR INSERT WITH CHECK (auth.role() = 'service_role');

CREATE POLICY vehicles_update_service ON public.vehicles
  FOR UPDATE USING (auth.role() = 'service_role');

CREATE POLICY vehicles_delete_service ON public.vehicles
  FOR DELETE USING (auth.role() = 'service_role');

-- ============================================================================
-- Policies: depreciation_curves
-- All authenticated can read; admins can write
-- ============================================================================
CREATE POLICY depreciation_curves_select ON public.depreciation_curves
  FOR SELECT USING (true);

CREATE POLICY depreciation_curves_insert ON public.depreciation_curves
  FOR INSERT WITH CHECK (public.current_user_role() = 'admin');

CREATE POLICY depreciation_curves_update ON public.depreciation_curves
  FOR UPDATE USING (public.current_user_role() = 'admin');

CREATE POLICY depreciation_curves_delete ON public.depreciation_curves
  FOR DELETE USING (public.current_user_role() = 'admin');

-- ============================================================================
-- Policies: simulations
-- Users can CRUD their own; admins can read all
-- ============================================================================
CREATE POLICY simulations_select ON public.simulations
  FOR SELECT USING (
    user_id = auth.uid() OR public.current_user_role() = 'admin'
  );

CREATE POLICY simulations_insert ON public.simulations
  FOR INSERT WITH CHECK (
    user_id = auth.uid()
  );

CREATE POLICY simulations_update ON public.simulations
  FOR UPDATE USING (
    user_id = auth.uid()
  );

CREATE POLICY simulations_delete ON public.simulations
  FOR DELETE USING (
    user_id = auth.uid()
  );

-- simulation_params inherits access via simulation ownership
CREATE POLICY simulation_params_select ON public.simulation_params
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.simulations s
      WHERE s.id = simulation_id
        AND (s.user_id = auth.uid() OR public.current_user_role() = 'admin')
    )
  );

CREATE POLICY simulation_params_insert ON public.simulation_params
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.simulations s
      WHERE s.id = simulation_id AND s.user_id = auth.uid()
    )
  );

CREATE POLICY simulation_params_update ON public.simulation_params
  FOR UPDATE USING (
    EXISTS (
      SELECT 1 FROM public.simulations s
      WHERE s.id = simulation_id AND s.user_id = auth.uid()
    )
  );

CREATE POLICY simulation_params_delete ON public.simulation_params
  FOR DELETE USING (
    EXISTS (
      SELECT 1 FROM public.simulations s
      WHERE s.id = simulation_id AND s.user_id = auth.uid()
    )
  );

-- ============================================================================
-- Policies: scraping_logs
-- Admins can read; service_role can write
-- ============================================================================
CREATE POLICY scraping_logs_select ON public.scraping_logs
  FOR SELECT USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY scraping_logs_insert_service ON public.scraping_logs
  FOR INSERT WITH CHECK (auth.role() = 'service_role');

CREATE POLICY scraping_logs_update_service ON public.scraping_logs
  FOR UPDATE USING (auth.role() = 'service_role');

-- ============================================================================
-- Policies: vehicle_price_history
-- Admins can read; service_role can write
-- ============================================================================
CREATE POLICY vehicle_price_history_select ON public.vehicle_price_history
  FOR SELECT USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY vehicle_price_history_insert_service ON public.vehicle_price_history
  FOR INSERT WITH CHECK (auth.role() = 'service_role');
