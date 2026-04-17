-- ============================================================================
-- Migration: 20260417000009_yayoi_settings
-- Description: Per-user Yayoi integration preferences + sync audit log.
--              * user_integration_settings — one row per user, stores
--                Yayoi auto-sync / invoice-sync / journal-sync toggles.
--              * yayoi_sync_log           — append-only history of every
--                sync attempt (referenced by YayoiService._log_sync and the
--                new GET /sync-log endpoint).
--              * RLS: users read/write their own settings row; sync log is
--                visible to authenticated users (service role writes it).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: user_integration_settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_integration_settings (
  id                          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                     uuid         NOT NULL UNIQUE
                                           REFERENCES public.users(id) ON DELETE CASCADE,
  yayoi_auto_sync_monthly     boolean      NOT NULL DEFAULT false,
  yayoi_sync_invoices         boolean      NOT NULL DEFAULT true,
  yayoi_sync_journals         boolean      NOT NULL DEFAULT true,
  created_at                  timestamptz  NOT NULL DEFAULT now(),
  updated_at                  timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.user_integration_settings IS
  'Per-user integration preferences (Yayoi for now; may hold other providers later).';
COMMENT ON COLUMN public.user_integration_settings.yayoi_auto_sync_monthly IS
  'If true, scheduler runs monthly Yayoi sync on day 5 at 02:00 JST.';
COMMENT ON COLUMN public.user_integration_settings.yayoi_sync_invoices IS
  'If true, approved invoices are posted to Yayoi as journal entries.';
COMMENT ON COLUMN public.user_integration_settings.yayoi_sync_journals IS
  'If true, full journal entries (incl. payment receipts) are synced.';

CREATE INDEX IF NOT EXISTS idx_user_integration_settings_user_id
  ON public.user_integration_settings (user_id);

CREATE TRIGGER trg_user_integration_settings_updated_at
  BEFORE UPDATE ON public.user_integration_settings
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: yayoi_sync_log
-- ---------------------------------------------------------------------------
-- YayoiService._log_sync already writes to this table. Create it here
-- (idempotently) so the integration works end-to-end.
CREATE TABLE IF NOT EXISTS public.yayoi_sync_log (
  id             uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  sync_type      text         NOT NULL,
  reference      text         NOT NULL,
  status         text         NOT NULL
                              CHECK (status IN ('success', 'failed', 'skipped', 'dry_run')),
  external_id    text,
  error_message  text,
  created_at     timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.yayoi_sync_log IS
  'Append-only log of every Yayoi sync attempt (journal entries, payments, batch runs).';
COMMENT ON COLUMN public.yayoi_sync_log.sync_type IS
  'One of: journal_entry | payment_entry | batch_invoices | monthly_auto.';
COMMENT ON COLUMN public.yayoi_sync_log.reference IS
  'Business key of the synced record, e.g. invoice_number or fund_id:month.';

CREATE INDEX IF NOT EXISTS idx_yayoi_sync_log_created_at
  ON public.yayoi_sync_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_yayoi_sync_log_type_status
  ON public.yayoi_sync_log (sync_type, status, created_at DESC);

-- ============================================================================
-- Row-Level Security
-- ============================================================================
ALTER TABLE public.user_integration_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yayoi_sync_log            ENABLE ROW LEVEL SECURITY;

-- user_integration_settings: a user can only see / modify their own row.
CREATE POLICY user_integration_settings_select ON public.user_integration_settings
  FOR SELECT USING (
    user_id = auth.uid()
    OR public.current_user_role() = 'admin'
  );

CREATE POLICY user_integration_settings_insert ON public.user_integration_settings
  FOR INSERT WITH CHECK (
    user_id = auth.uid()
    OR public.current_user_role() = 'admin'
  );

CREATE POLICY user_integration_settings_update ON public.user_integration_settings
  FOR UPDATE USING (
    user_id = auth.uid()
    OR public.current_user_role() = 'admin'
  );

CREATE POLICY user_integration_settings_delete ON public.user_integration_settings
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- yayoi_sync_log: any authenticated user may read the log (it contains no
-- user-level PII); writes are done by the service-role client from the
-- YayoiService, so no INSERT policy is required for end-users.
CREATE POLICY yayoi_sync_log_select ON public.yayoi_sync_log
  FOR SELECT USING (auth.role() = 'authenticated' OR public.current_user_role() = 'admin');
