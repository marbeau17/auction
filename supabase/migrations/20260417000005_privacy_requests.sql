-- ============================================================================
-- Migration: 20260417000005_privacy_requests
-- Description: APPI (Japan 改正個人情報保護法) + GDPR parity.
--              * privacy_deletion_requests table (workflow: pending_review
--                -> approved / rejected -> executed)
--              * Adds soft-delete / redaction columns to users
--              * RLS: users see own requests; admins see & mutate all
--
-- NOTE: Actual redaction is performed at application level (see
--       app.db.repositories.privacy_repo.execute_redaction).  Financial /
--       accounting rows (invoices, lease_payments, simulations, ...) are
--       NEVER hard-deleted because Japanese tax law (法人税法) imposes a
--       7-year retention requirement on accounting documents.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- users: soft-delete + redaction flags
-- ---------------------------------------------------------------------------
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS is_deleted   boolean      NOT NULL DEFAULT false;

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS deleted_at   timestamptz;

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS redacted_at  timestamptz;

COMMENT ON COLUMN public.users.is_deleted
  IS 'Soft-delete flag set after APPI/GDPR right-to-erasure execution.';
COMMENT ON COLUMN public.users.deleted_at
  IS 'Timestamp the deletion request was executed.';
COMMENT ON COLUMN public.users.redacted_at
  IS 'Timestamp PII (email/full_name/etc) was scrubbed.';

-- ---------------------------------------------------------------------------
-- Table: privacy_deletion_requests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.privacy_deletion_requests (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  requested_at  timestamptz NOT NULL DEFAULT now(),
  reason        text,
  status        text        NOT NULL DEFAULT 'pending_review'
                            CHECK (status IN ('pending_review', 'approved', 'executed', 'rejected')),
  reviewed_by   uuid        REFERENCES public.users(id) ON DELETE SET NULL,
  reviewed_at   timestamptz,
  executed_at   timestamptz,
  notes         text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.privacy_deletion_requests
  IS 'APPI/GDPR right-to-erasure workflow queue. Admin reviews each request before execution because APPI requires identity verification and tax law requires 7-year retention of accounting rows.';

CREATE INDEX IF NOT EXISTS idx_privacy_deletion_requests_status
  ON public.privacy_deletion_requests (status, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_privacy_deletion_requests_user
  ON public.privacy_deletion_requests (user_id, requested_at DESC);

CREATE TRIGGER trg_privacy_deletion_requests_updated_at
  BEFORE UPDATE ON public.privacy_deletion_requests
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ============================================================================
-- Row-Level Security
-- ============================================================================
ALTER TABLE public.privacy_deletion_requests ENABLE ROW LEVEL SECURITY;

-- SELECT: a user can see their own request; admins see everything.
CREATE POLICY privacy_deletion_requests_select ON public.privacy_deletion_requests
  FOR SELECT USING (
    user_id = auth.uid()
    OR public.current_user_role() = 'admin'
  );

-- INSERT: any authenticated user may file a request for themselves.
CREATE POLICY privacy_deletion_requests_insert ON public.privacy_deletion_requests
  FOR INSERT WITH CHECK (
    user_id = auth.uid()
    OR public.current_user_role() = 'admin'
  );

-- UPDATE: admin only (review / approve / reject / mark executed).
CREATE POLICY privacy_deletion_requests_update ON public.privacy_deletion_requests
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

-- DELETE: admin only (should be rare; generally keep the audit row).
CREATE POLICY privacy_deletion_requests_delete ON public.privacy_deletion_requests
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );
