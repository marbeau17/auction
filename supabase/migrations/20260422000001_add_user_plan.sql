-- ============================================================================
-- Migration: 20260422000001_add_user_plan
-- Description: Add subscription-tier column to users for 松プラン UI gating.
-- ============================================================================
-- Tiers: ume (basic) < take (standard) < matsu (premium) < enterprise (reserved)
-- The 'enterprise' slot is reserved extra capacity per
-- docs/uiux_migration_spec.md §5 / 2026-04-22 decision.
-- ----------------------------------------------------------------------------

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS plan text NOT NULL DEFAULT 'take'
    CHECK (plan IN ('ume', 'take', 'matsu', 'enterprise'));

COMMENT ON COLUMN public.users.plan IS
  'Subscription tier. ume<take<matsu<enterprise. Gates 松限定 routes (/risk, /scrape, /esg) and Dashboard B/C variants. See docs/uiux_migration_spec.md §5.';

CREATE INDEX IF NOT EXISTS idx_users_plan ON public.users(plan);

-- Existing admin users are granted matsu so the operator team retains
-- access to the premium-only pages built in the 2026-04-22 redesign.
UPDATE public.users
   SET plan = 'matsu'
 WHERE role = 'admin'
   AND plan = 'take';
