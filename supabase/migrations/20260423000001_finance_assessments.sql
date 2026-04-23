-- ============================================================================
-- Migration: 20260423000001_finance_assessments
-- Description: Storage for LLM-extracted 決算書 diagnoses. Cross-fund scope
--              (fund_id nullable, loose tag only — no RLS effect). 7-year
--              retention per Japanese tax law (法人税法 施行規則 第59条);
--              purged nightly by scripts/cron/purge_expired_assessments.py.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: finance_assessments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.finance_assessments (
  id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           uuid         NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  fund_id           uuid         REFERENCES public.funds(id) ON DELETE SET NULL,
  pdf_sha256        text         NOT NULL,
  needs_vision      boolean      NOT NULL DEFAULT false,
  extracted_input   jsonb        NOT NULL,
  diagnosis         jsonb        NOT NULL,
  narrative         text,
  model             text         NOT NULL,
  cost_usd          numeric(10,4) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  retention_until   timestamptz  NOT NULL DEFAULT (now() + interval '7 years'),
  created_at        timestamptz  NOT NULL DEFAULT now(),
  updated_at        timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.finance_assessments IS
  'LLM-extracted 決算書 (financial statement) diagnoses. Cross-fund feature — fund_id is a loose tag only; authorisation happens at the application layer via RBAC.';

COMMENT ON COLUMN public.finance_assessments.fund_id IS
  'Loose tag only; not used for authorization (cross-fund feature).';
COMMENT ON COLUMN public.finance_assessments.pdf_sha256 IS
  'SHA-256 of the uploaded PDF. Dedup key: same user + same PDF re-uses the cached diagnosis.';
COMMENT ON COLUMN public.finance_assessments.needs_vision IS
  'True when the text layer was empty and Gemini''s vision path was used (doubles token cost).';
COMMENT ON COLUMN public.finance_assessments.extracted_input IS
  'FinancialInput fields (26 Japanese line items) as extracted by the LLM.';
COMMENT ON COLUMN public.finance_assessments.diagnosis IS
  'FinancialDiagnosisResult from the deterministic rule engine.';
COMMENT ON COLUMN public.finance_assessments.narrative IS
  'Optional LLM-authored commentary paragraph; nullable.';
COMMENT ON COLUMN public.finance_assessments.model IS
  'Snapshot of the model + date stamp, e.g. ''gemini-flash-latest@2026-04-23''.';
COMMENT ON COLUMN public.finance_assessments.cost_usd IS
  'Estimated inference cost in USD for budget tracking.';
COMMENT ON COLUMN public.finance_assessments.retention_until IS
  'Row is purged after this timestamp. 7-year default per 法人税法 施行規則 第59条.';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Primary list endpoint: user's assessments most-recent-first
CREATE INDEX IF NOT EXISTS idx_finance_assessments_user
  ON public.finance_assessments (user_id, created_at DESC);

-- Dedup: same user re-uploading the same PDF hits the cache. Different
-- users may both re-extract the same PDF (their narratives could
-- reference distinct client context, so sharing would leak PII).
CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_assessments_user_hash
  ON public.finance_assessments (user_id, pdf_sha256);

-- Purge cron: scan rows whose retention window has elapsed
CREATE INDEX IF NOT EXISTS idx_finance_assessments_retention
  ON public.finance_assessments (retention_until);

-- General listing (cross-user admin views)
CREATE INDEX IF NOT EXISTS idx_finance_assessments_created_at
  ON public.finance_assessments (created_at DESC);

-- Loose filter for the "by fund" report view
CREATE INDEX IF NOT EXISTS idx_finance_assessments_fund_id
  ON public.finance_assessments (fund_id);

-- ---------------------------------------------------------------------------
-- Trigger: updated_at auto-maintenance
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_finance_assessments_updated_at
  ON public.finance_assessments;
CREATE TRIGGER trg_finance_assessments_updated_at
  BEFORE UPDATE ON public.finance_assessments
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ============================================================================
-- Row-Level Security
-- ============================================================================
ALTER TABLE public.finance_assessments ENABLE ROW LEVEL SECURITY;

-- SELECT: owner or admin
DROP POLICY IF EXISTS finance_assessments_select ON public.finance_assessments;
CREATE POLICY finance_assessments_select ON public.finance_assessments
  FOR SELECT USING (
    user_id = auth.uid()
    OR public.current_user_role() = 'admin'
  );

-- INSERT: owner or service_role (server-side inserts)
DROP POLICY IF EXISTS finance_assessments_insert ON public.finance_assessments;
CREATE POLICY finance_assessments_insert ON public.finance_assessments
  FOR INSERT WITH CHECK (
    user_id = auth.uid()
    OR auth.role() = 'service_role'
  );

-- UPDATE: admin only (records should be append-only for audit)
DROP POLICY IF EXISTS finance_assessments_update ON public.finance_assessments;
CREATE POLICY finance_assessments_update ON public.finance_assessments
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

-- DELETE: owner (GDPR-adjacent manual delete), service_role (purge cron),
-- or admin (manual moderation).
DROP POLICY IF EXISTS finance_assessments_delete ON public.finance_assessments;
CREATE POLICY finance_assessments_delete ON public.finance_assessments
  FOR DELETE USING (
    user_id = auth.uid()
    OR auth.role() = 'service_role'
    OR public.current_user_role() = 'admin'
  );
