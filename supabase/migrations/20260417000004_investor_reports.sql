-- ============================================================================
-- Migration: 20260417000004_investor_reports
-- Description: Monthly per-fund investor statement PDFs and signed-URL
--              access audit logs (investor dashboard spec — INV-004).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: investor_reports
-- ---------------------------------------------------------------------------
CREATE TABLE public.investor_reports (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id             uuid        NOT NULL REFERENCES public.funds(id) ON DELETE CASCADE,
  report_month        date        NOT NULL,
  generated_at        timestamptz NOT NULL DEFAULT now(),
  storage_path        text        NOT NULL,
  nav_total           bigint      NOT NULL DEFAULT 0,
  dividend_paid       bigint      NOT NULL DEFAULT 0,
  dividend_scheduled  bigint      NOT NULL DEFAULT 0,
  risk_flags          jsonb       NOT NULL DEFAULT '[]'::jsonb,
  generated_by        uuid        REFERENCES public.users(id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),

  -- report_month must be the first-of-month (we still store a DATE to keep
  -- downstream BI joins simple).
  CONSTRAINT chk_report_month_first_of_month
    CHECK (date_trunc('month', report_month)::date = report_month),

  CONSTRAINT uq_investor_reports_fund_month UNIQUE (fund_id, report_month)
);

COMMENT ON TABLE  public.investor_reports IS
  'Monthly per-fund investor statement (NAV / dividend / risk). Storage path points to generated PDF in Supabase Storage.';
COMMENT ON COLUMN public.investor_reports.report_month IS
  'Reporting period anchor — always the first of the month (YYYY-MM-01).';
COMMENT ON COLUMN public.investor_reports.storage_path IS
  'Object path within the investor-reports bucket, e.g. "<fund_id>/2026-04.pdf".';
COMMENT ON COLUMN public.investor_reports.risk_flags IS
  'JSONB array of risk flag objects: [{code, severity, message, ...}, ...]';

CREATE INDEX idx_investor_reports_fund_id      ON public.investor_reports (fund_id);
CREATE INDEX idx_investor_reports_report_month ON public.investor_reports (report_month DESC);
CREATE INDEX idx_investor_reports_fund_month   ON public.investor_reports (fund_id, report_month DESC);

CREATE TRIGGER trg_investor_reports_updated_at
  BEFORE UPDATE ON public.investor_reports
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: investor_report_access_logs
-- ---------------------------------------------------------------------------
CREATE TABLE public.investor_report_access_logs (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id         uuid        NOT NULL REFERENCES public.investor_reports(id) ON DELETE CASCADE,
  accessed_by       uuid        REFERENCES public.users(id),
  signed_url_hash   text        NOT NULL,
  expires_at        timestamptz NOT NULL,
  downloaded_at     timestamptz,
  ip_address        inet,
  created_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.investor_report_access_logs IS
  'Audit trail for signed-URL issuance + PDF download per investor_reports row.';
COMMENT ON COLUMN public.investor_report_access_logs.signed_url_hash IS
  'SHA-256 hash of the issued HMAC token (we never persist the token itself).';
COMMENT ON COLUMN public.investor_report_access_logs.downloaded_at IS
  'Null until the signed URL is actually redeemed — set on download endpoint hit.';

CREATE INDEX idx_investor_report_access_logs_report_id   ON public.investor_report_access_logs (report_id);
CREATE INDEX idx_investor_report_access_logs_accessed_by ON public.investor_report_access_logs (accessed_by);
CREATE INDEX idx_investor_report_access_logs_expires_at  ON public.investor_report_access_logs (expires_at);
CREATE INDEX idx_investor_report_access_logs_hash        ON public.investor_report_access_logs (signed_url_hash);

-- ============================================================================
-- Row Level Security
-- ============================================================================

-- investor_reports ------------------------------------------------------------
ALTER TABLE public.investor_reports ENABLE ROW LEVEL SECURITY;

-- SELECT: admins see all; investors see only their own fund's reports.
-- Investor scope is determined via fund_investors joined on the authenticated
-- user's email (preferred) or — per spec — via deal_stakeholders (sim-scoped
-- attendees). We union both so downstream wiring can land either way.
CREATE POLICY investor_reports_select ON public.investor_reports
  FOR SELECT USING (
    public.current_user_role() = 'admin'
    OR EXISTS (
      SELECT 1
      FROM public.fund_investors fi
      JOIN public.users u
        ON lower(u.email) = lower(fi.investor_contact_email)
      WHERE fi.fund_id = investor_reports.fund_id
        AND u.id = auth.uid()
        AND fi.is_active = true
    )
    OR EXISTS (
      -- Fallback: investor role-mapped via deal_stakeholders (spec §9)
      SELECT 1
      FROM public.deal_stakeholders ds
      JOIN public.simulations s ON s.id = ds.simulation_id
      JOIN public.users u       ON lower(u.email) = lower(ds.email)
      WHERE ds.role_type = 'investor'
        AND u.id = auth.uid()
        AND s.fund_id = investor_reports.fund_id
    )
  );

-- INSERT: admins + service_role (scheduler uses service_role key)
CREATE POLICY investor_reports_insert ON public.investor_reports
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );

CREATE POLICY investor_reports_update ON public.investor_reports
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );

CREATE POLICY investor_reports_delete ON public.investor_reports
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- investor_report_access_logs ------------------------------------------------
ALTER TABLE public.investor_report_access_logs ENABLE ROW LEVEL SECURITY;

-- SELECT: admins only (audit data is not investor-visible).
CREATE POLICY investor_report_access_logs_select ON public.investor_report_access_logs
  FOR SELECT USING (
    public.current_user_role() = 'admin'
  );

-- INSERT: admin + service_role (the API writes rows using service-role key
-- during signed-URL issuance and download redemption).
CREATE POLICY investor_report_access_logs_insert ON public.investor_report_access_logs
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );

-- UPDATE (only used to flip downloaded_at): admin + service_role.
CREATE POLICY investor_report_access_logs_update ON public.investor_report_access_logs
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
    OR auth.role() = 'service_role'
  );
