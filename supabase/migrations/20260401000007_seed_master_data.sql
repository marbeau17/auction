-- ============================================================================
-- Migration: 20260401000007_seed_master_data
-- Description: Seed vehicle_categories, manufacturers, body_types,
--              and default depreciation curves
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Vehicle Categories
-- ---------------------------------------------------------------------------
INSERT INTO public.vehicle_categories (name, code, display_order) VALUES
  ('大型トラック',       'LARGE',            1),
  ('中型トラック',       'MEDIUM',           2),
  ('小型トラック',       'SMALL',            3),
  ('トレーラーヘッド',   'TRAILER_HEAD',     4),
  ('トレーラーシャシー', 'TRAILER_CHASSIS',  5);

-- ---------------------------------------------------------------------------
-- Manufacturers
-- ---------------------------------------------------------------------------
INSERT INTO public.manufacturers (name, name_en, code, country, display_order) VALUES
  ('いすゞ',       'Isuzu',            'ISZ', 'JP', 1),
  ('日野',         'Hino',             'HNO', 'JP', 2),
  ('三菱ふそう',   'Mitsubishi Fuso',  'MFU', 'JP', 3),
  ('UDトラックス', 'UD Trucks',        'UDT', 'JP', 4);

-- ---------------------------------------------------------------------------
-- Body Types
-- ---------------------------------------------------------------------------
INSERT INTO public.body_types (name, code, display_order) VALUES
  ('ウイング',       'WING', 1),
  ('バン',           'VAN',  2),
  ('平ボディ',       'FLAT', 3),
  ('冷凍冷蔵車',     'REFR', 4),
  ('ダンプ',         'DUMP', 5),
  ('クレーン付き',   'CRAN', 6),
  ('タンクローリー', 'TANK', 7),
  ('塵芥車',         'TRSH', 8),
  ('ミキサー',       'MIXR', 9),
  ('キャリアカー',   'CARR', 10);

-- ---------------------------------------------------------------------------
-- Depreciation Curves
--
-- Realistic defaults for commercial vehicles in Japan:
--   Large trucks:      7-year useful life, 10% residual, linear
--   Medium trucks:     6-year useful life, 10% residual, linear
--   Small trucks:      5-year useful life, 10% residual, linear
--   Trailer heads:     8-year useful life, 8% residual, declining balance
--   Trailer chassis:  10-year useful life, 5% residual, linear
-- ---------------------------------------------------------------------------
INSERT INTO public.depreciation_curves
  (category_id, curve_type, useful_life_years, residual_rate, notes)
VALUES
  (
    (SELECT id FROM public.vehicle_categories WHERE code = 'LARGE'),
    'linear', 7, 0.1000,
    'Default: large trucks, 7-year straight-line, 10% residual'
  ),
  (
    (SELECT id FROM public.vehicle_categories WHERE code = 'MEDIUM'),
    'linear', 6, 0.1000,
    'Default: medium trucks, 6-year straight-line, 10% residual'
  ),
  (
    (SELECT id FROM public.vehicle_categories WHERE code = 'SMALL'),
    'linear', 5, 0.1000,
    'Default: small trucks, 5-year straight-line, 10% residual'
  ),
  (
    (SELECT id FROM public.vehicle_categories WHERE code = 'TRAILER_HEAD'),
    'declining_balance', 8, 0.0800,
    'Default: trailer heads, 8-year declining balance, 8% residual'
  ),
  (
    (SELECT id FROM public.vehicle_categories WHERE code = 'TRAILER_CHASSIS'),
    'linear', 10, 0.0500,
    'Default: trailer chassis, 10-year straight-line, 5% residual'
  );
