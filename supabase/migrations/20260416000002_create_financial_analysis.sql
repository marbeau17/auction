-- ============================================================================
-- Migration: 20260416000002_create_financial_analysis
-- Description: Create financial analysis history and alert tables for
--              lessee creditworthiness diagnostics
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: financial_analyses
-- ---------------------------------------------------------------------------
CREATE TABLE public.financial_analyses (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name        text        NOT NULL,
  analysis_date       date        NOT NULL DEFAULT CURRENT_DATE,
  input_data          jsonb       NOT NULL,
  result              jsonb       NOT NULL,
  score               text        NOT NULL
                                  CHECK (score IN ('A', 'B', 'C', 'D')),
  risk_level          text        NOT NULL,
  max_monthly_lease   bigint,
  analyzed_by         uuid        REFERENCES public.users(id),
  simulation_id       uuid        REFERENCES public.simulations(id),
  notes               text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.financial_analyses IS 'Financial diagnosis history — stores creditworthiness analysis per lessee company';
COMMENT ON COLUMN public.financial_analyses.input_data IS 'Raw FinancialAnalysisInput JSON submitted by the analyst';
COMMENT ON COLUMN public.financial_analyses.result IS 'Computed FinancialDiagnosisResult JSON (ratios, flags, narrative)';
COMMENT ON COLUMN public.financial_analyses.score IS 'Overall credit score grade: A (excellent) to D (high risk)';
COMMENT ON COLUMN public.financial_analyses.risk_level IS 'Human-readable risk label (e.g. low, moderate, high, critical)';
COMMENT ON COLUMN public.financial_analyses.max_monthly_lease IS 'Maximum recommended monthly lease amount in JPY';
COMMENT ON COLUMN public.financial_analyses.simulation_id IS 'Optional link to a pricing simulation for integrated analysis';

-- Indexes
CREATE INDEX idx_financial_analyses_company_name
  ON public.financial_analyses (company_name);

CREATE INDEX idx_financial_analyses_score
  ON public.financial_analyses (score);

CREATE INDEX idx_financial_analyses_analysis_date
  ON public.financial_analyses (analysis_date DESC);

CREATE INDEX idx_financial_analyses_analyzed_by
  ON public.financial_analyses (analyzed_by);

CREATE INDEX idx_financial_analyses_simulation
  ON public.financial_analyses (simulation_id)
  WHERE simulation_id IS NOT NULL;

-- Trigger
CREATE TRIGGER trg_financial_analyses_updated_at
  BEFORE UPDATE ON public.financial_analyses
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: financial_analysis_alerts
-- ---------------------------------------------------------------------------
CREATE TABLE public.financial_analysis_alerts (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  financial_analysis_id uuid        NOT NULL REFERENCES public.financial_analyses(id) ON DELETE CASCADE,
  alert_type            text        NOT NULL
                                    CHECK (alert_type IN ('warning', 'recommendation', 'improvement')),
  message               text        NOT NULL,
  severity              text        CHECK (severity IN ('high', 'medium', 'low')),
  created_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.financial_analysis_alerts IS 'Alerts generated from a financial analysis — warnings, recommendations, and improvement suggestions';
COMMENT ON COLUMN public.financial_analysis_alerts.alert_type IS 'Category: warning (risk flag), recommendation (action item), improvement (positive opportunity)';
COMMENT ON COLUMN public.financial_analysis_alerts.severity IS 'Impact severity: high, medium, or low';

-- Indexes
CREATE INDEX idx_financial_analysis_alerts_analysis
  ON public.financial_analysis_alerts (financial_analysis_id);

CREATE INDEX idx_financial_analysis_alerts_type
  ON public.financial_analysis_alerts (alert_type);

CREATE INDEX idx_financial_analysis_alerts_severity
  ON public.financial_analysis_alerts (severity)
  WHERE severity IS NOT NULL;

-- ============================================================================
-- Row Level Security
-- ============================================================================
ALTER TABLE public.financial_analyses       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.financial_analysis_alerts ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- Policies: financial_analyses
-- Analysts can CRUD their own records; admins can read/write all
-- ---------------------------------------------------------------------------
CREATE POLICY financial_analyses_select ON public.financial_analyses
  FOR SELECT USING (
    analyzed_by = auth.uid() OR public.current_user_role() = 'admin'
  );

CREATE POLICY financial_analyses_insert ON public.financial_analyses
  FOR INSERT WITH CHECK (
    analyzed_by = auth.uid()
  );

CREATE POLICY financial_analyses_update ON public.financial_analyses
  FOR UPDATE USING (
    analyzed_by = auth.uid() OR public.current_user_role() = 'admin'
  );

CREATE POLICY financial_analyses_delete ON public.financial_analyses
  FOR DELETE USING (
    analyzed_by = auth.uid() OR public.current_user_role() = 'admin'
  );

-- ---------------------------------------------------------------------------
-- Policies: financial_analysis_alerts
-- Inherit access via parent financial_analyses ownership
-- ---------------------------------------------------------------------------
CREATE POLICY financial_analysis_alerts_select ON public.financial_analysis_alerts
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.financial_analyses fa
      WHERE fa.id = financial_analysis_id
        AND (fa.analyzed_by = auth.uid() OR public.current_user_role() = 'admin')
    )
  );

CREATE POLICY financial_analysis_alerts_insert ON public.financial_analysis_alerts
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.financial_analyses fa
      WHERE fa.id = financial_analysis_id
        AND (fa.analyzed_by = auth.uid() OR public.current_user_role() = 'admin')
    )
  );

CREATE POLICY financial_analysis_alerts_update ON public.financial_analysis_alerts
  FOR UPDATE USING (
    EXISTS (
      SELECT 1 FROM public.financial_analyses fa
      WHERE fa.id = financial_analysis_id
        AND (fa.analyzed_by = auth.uid() OR public.current_user_role() = 'admin')
    )
  );

CREATE POLICY financial_analysis_alerts_delete ON public.financial_analysis_alerts
  FOR DELETE USING (
    EXISTS (
      SELECT 1 FROM public.financial_analyses fa
      WHERE fa.id = financial_analysis_id
        AND (fa.analyzed_by = auth.uid() OR public.current_user_role() = 'admin')
    )
  );
