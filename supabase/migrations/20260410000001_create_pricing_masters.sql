-- =============================================================
-- Migration: Create pricing_masters & pricing_parameter_history
-- CVLPOS: Commercial Vehicle Leaseback Pricing Optimization
-- =============================================================

-- -------------------------------------------------------------
-- 1. pricing_masters
-- -------------------------------------------------------------
CREATE TABLE public.pricing_masters (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name                  TEXT        NOT NULL,
  description           TEXT,
  fund_id               UUID        REFERENCES public.funds(id),
  investor_yield_rate   NUMERIC(6,4) NOT NULL DEFAULT 0.0800,
  am_fee_rate           NUMERIC(6,4) NOT NULL DEFAULT 0.0200,
  placement_fee_rate    NUMERIC(6,4) NOT NULL DEFAULT 0.0300,
  accounting_fee_monthly BIGINT     NOT NULL DEFAULT 50000,
  operator_margin_rate  NUMERIC(6,4) NOT NULL DEFAULT 0.0200,
  safety_margin_rate    NUMERIC(6,4) NOT NULL DEFAULT 0.0500,
  depreciation_method   TEXT        NOT NULL DEFAULT 'declining_200'
                        CHECK (depreciation_method IN ('declining_200', 'straight_line')),
  is_active             BOOLEAN     DEFAULT true,
  created_at            TIMESTAMPTZ DEFAULT now(),
  updated_at            TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE public.pricing_masters IS 'プライシングマスタ — リースバック価格算出パラメータ';
COMMENT ON COLUMN public.pricing_masters.investor_yield_rate IS '投資家利回り（年率）';
COMMENT ON COLUMN public.pricing_masters.am_fee_rate IS 'AM手数料率（年率）';
COMMENT ON COLUMN public.pricing_masters.placement_fee_rate IS 'プレイスメントフィー率（一括）';
COMMENT ON COLUMN public.pricing_masters.accounting_fee_monthly IS '会計事務手数料（月額・円）';
COMMENT ON COLUMN public.pricing_masters.operator_margin_rate IS 'オペレータマージン率';
COMMENT ON COLUMN public.pricing_masters.safety_margin_rate IS '安全マージン率';
COMMENT ON COLUMN public.pricing_masters.depreciation_method IS '減価償却方法: declining_200=200%定率法, straight_line=定額法';

-- Indexes
CREATE INDEX idx_pricing_masters_fund_id   ON public.pricing_masters (fund_id);
CREATE INDEX idx_pricing_masters_is_active ON public.pricing_masters (is_active);

-- Updated-at trigger
CREATE TRIGGER trg_pricing_masters_updated_at
  BEFORE UPDATE ON public.pricing_masters
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- -------------------------------------------------------------
-- 2. pricing_parameter_history
-- -------------------------------------------------------------
CREATE TABLE public.pricing_parameter_history (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  pricing_master_id UUID        NOT NULL REFERENCES public.pricing_masters(id) ON DELETE CASCADE,
  parameter_key     TEXT        NOT NULL,
  old_value         JSONB,
  new_value         JSONB       NOT NULL,
  changed_by        UUID        REFERENCES public.users(id),
  changed_at        TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE public.pricing_parameter_history IS 'プライシングパラメータ変更履歴';

-- Index
CREATE INDEX idx_pricing_parameter_history_master_id
  ON public.pricing_parameter_history (pricing_master_id);

-- -------------------------------------------------------------
-- 3. Row Level Security
-- -------------------------------------------------------------

-- pricing_masters
ALTER TABLE public.pricing_masters ENABLE ROW LEVEL SECURITY;

CREATE POLICY pricing_masters_select ON public.pricing_masters
  FOR SELECT TO authenticated USING (true);

CREATE POLICY pricing_masters_insert ON public.pricing_masters
  FOR INSERT WITH CHECK (public.current_user_role() = 'admin');

CREATE POLICY pricing_masters_update ON public.pricing_masters
  FOR UPDATE USING (public.current_user_role() = 'admin');

CREATE POLICY pricing_masters_delete ON public.pricing_masters
  FOR DELETE USING (public.current_user_role() = 'admin');

-- pricing_parameter_history
ALTER TABLE public.pricing_parameter_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY pricing_parameter_history_select ON public.pricing_parameter_history
  FOR SELECT TO authenticated USING (true);

CREATE POLICY pricing_parameter_history_insert ON public.pricing_parameter_history
  FOR INSERT WITH CHECK (public.current_user_role() = 'admin');

CREATE POLICY pricing_parameter_history_update ON public.pricing_parameter_history
  FOR UPDATE USING (public.current_user_role() = 'admin');

CREATE POLICY pricing_parameter_history_delete ON public.pricing_parameter_history
  FOR DELETE USING (public.current_user_role() = 'admin');

-- -------------------------------------------------------------
-- 4. Seed default pricing master
-- -------------------------------------------------------------
INSERT INTO public.pricing_masters (name, description)
VALUES (
  'デフォルトプライシング設定',
  '全ファンド共通のデフォルトプライシングパラメータ。ファンド固有設定がない場合に使用。'
);
