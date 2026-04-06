# Carchs ピッチデッキ要件に基づく GAP分析・適応計画

> 作成日: 2026-04-06
> 対象リポジトリ: https://github.com/marbeau17/auction
> デプロイ先: https://auction-ten-iota.vercel.app

---

## 1. 現行システムとのGAP分析

| # | 領域 | 現行実装 | 新要件（Carchs） | GAP | 影響度 |
|---|------|----------|-------------------|-----|--------|
| 1 | **価格算出ベース** | `PricingEngine.calculate_base_market_price()` でオークション価格とリテール価格の加重平均（auction_weight=0.70）を使用 | LTV 60%ルール: `max_purchase = B2B_wholesale × 0.60`。リテール価格は一切使用不可 | **大**: `calculate_base_market_price()` のロジック全面見直し。リテール価格の排除、B2B wholesale floorの導入が必要 | 高 |
| 2 | **最大購入価格** | `calculate_max_purchase_price()` で `base_market_price * condition * trend * (1 - safety_margin)` の計算式 | LTV 60%上限を厳格適用。`max_purchase = b2b_wholesale * 0.60` を超過不可 | **大**: 現行の計算式にLTV 60%キャップを追加。`DEFAULT_PARAMS` に `ltv_cap: 0.60` を追加 | 高 |
| 3 | **Valuation Stack** | 現行は `auction_prices` / `retail_prices` の2分類のみ | B2B wholesale floorを厳格に維持。retail価格は参考値のみ | **中**: 価格データの分類体系を3層（B2B wholesale / auction / retail）に拡張 | 高 |
| 4 | **オプション調整** | `SimulationInput.body_option_value` で一律の追加価値入力のみ | Power Gate、Cold Storage、Craneなどオプション別プレミアム率の個別計算 | **大**: オプションマスタテーブル新規追加。`OptionAdjustedValuation` クラスの新規実装 | 中 |
| 5 | **Value Transfer Engineering** | 未実装 | Net Fund Asset Value > 60%を常時維持。資産価値移転の工学的管理 | **大**: `ValueTransferEngine` クラスの完全新規実装。NAV計算ロジック追加 | 高 |
| 6 | **ファンド（SPC）管理** | 未実装。`users`テーブルのみ | ファンドエンティティ、投資家配分、利回り分配の管理 | **大**: `funds`, `fund_investors`, `fund_assets` 等のテーブル群、API、画面すべて新規 | 高 |
| 7 | **リース契約管理** | `simulations`テーブルでシミュレーション結果を保存するのみ。実契約管理なし | 支払いスケジュール、入金追跡、デフォルト検知 | **大**: `lease_contracts`, `lease_payments` テーブル群、支払い追跡ワークフロー全体が新規 | 高 |
| 8 | **デフォルト/Exit** | 未実装。`early_termination_penalty_months: 3` パラメータのみ存在 | T+0→T+1→T+3→T+10タイムライン管理、段階的エスカレーション | **大**: `defaults`, `default_events` テーブル、ワークフローエンジン、通知機能の新規実装 | 高 |
| 9 | **国際清算** | 未実装。国内市場データのスクレイピングのみ（truck-kingdom, steerlink） | 海外市場ルーティングによる資産回収 | **大**: `international_markets`, `liquidation_records` テーブル、海外市場コネクタの新規実装 | 中 |
| 10 | **投資家ダッシュボード** | 現行ダッシュボードは自分のシミュレーション履歴のみ（`pages/dashboard.html`） | ポートフォリオビュー、NAV推移、リスク監視 | **大**: 投資家向け専用画面群、リアルタイムNAV計算、リスク指標の新規実装 | 高 |
| 11 | **車両テレメトリ** | 未実装 | GPS・走行データ連携（将来） | Phase 3以降。現時点ではスキーマ予約のみ | 低 |
| 12 | **動的価格設定** | `calculate_trend_factor()` でトレンド係数計算はあるが静的パラメータ | リアルタイム市場データに基づく動的リプライシング | Phase 3以降 | 低 |
| 13 | **ESG対応** | 未実装 | EV転換対応、ESGスコアリング | Phase 3以降 | 低 |
| 14 | **ユーザーロール** | `users`テーブルに`role`カラムあり（authenticated/admin）| ファンドマネージャー、投資家、オペレーターなど多段階ロール | **中**: ロールマスタ追加、RBAC強化 | 中 |
| 15 | **レポーティング** | `scripts/export_report.py` のみ | 投資家向け定期レポート、NAVレポート、リスクレポート自動生成 | **大**: レポートテンプレート、PDF生成、配信機能の新規実装 | 中 |

---

## 2. データベーススキーマ変更一覧

### 2.1 既存テーブルの変更

#### `vehicles` テーブル（`supabase/migrations/20260401000002_create_vehicles.sql`）

```sql
-- 追加カラム
ALTER TABLE public.vehicles ADD COLUMN price_type text DEFAULT 'retail'
  CHECK (price_type IN ('b2b_wholesale', 'auction', 'retail'));
ALTER TABLE public.vehicles ADD COLUMN b2b_wholesale_price_yen bigint;
ALTER TABLE public.vehicles ADD COLUMN has_power_gate boolean DEFAULT false;
ALTER TABLE public.vehicles ADD COLUMN has_cold_storage boolean DEFAULT false;
ALTER TABLE public.vehicles ADD COLUMN has_crane boolean DEFAULT false;
ALTER TABLE public.vehicles ADD COLUMN option_details jsonb DEFAULT '{}';
ALTER TABLE public.vehicles ADD COLUMN international_market_id uuid;
```

#### `simulations` テーブル（`supabase/migrations/20260401000004_create_simulations.sql`）

```sql
-- 追加カラム
ALTER TABLE public.simulations ADD COLUMN fund_id uuid;
ALTER TABLE public.simulations ADD COLUMN ltv_ratio numeric(6,4);
ALTER TABLE public.simulations ADD COLUMN b2b_wholesale_price_yen bigint;
ALTER TABLE public.simulations ADD COLUMN option_adjusted_value_yen bigint;
ALTER TABLE public.simulations ADD COLUMN nav_at_creation numeric(18,4);
ALTER TABLE public.simulations ADD COLUMN valuation_method text DEFAULT 'b2b_wholesale';
```

#### `users` テーブル

```sql
-- 追加カラム
ALTER TABLE public.users ADD COLUMN user_role text DEFAULT 'operator'
  CHECK (user_role IN ('admin', 'fund_manager', 'investor', 'operator'));
```

### 2.2 新規テーブル一覧

#### マイグレーションファイル配置先: `supabase/migrations/`

| # | テーブル名 | ファイル名 | 用途 |
|---|-----------|-----------|------|
| 1 | `funds` | `20260407000001_create_funds.sql` | ファンド（SPC）エンティティ管理 |
| 2 | `fund_investors` | `20260407000002_create_fund_investors.sql` | 投資家のファンド出資配分 |
| 3 | `fund_assets` | `20260407000003_create_fund_assets.sql` | ファンド保有資産（車両）管理 |
| 4 | `fund_nav_history` | `20260407000004_create_fund_nav_history.sql` | NAV推移履歴 |
| 5 | `lease_contracts` | `20260407000005_create_lease_contracts.sql` | リース契約本体 |
| 6 | `lease_payments` | `20260407000006_create_lease_payments.sql` | リース支払い明細・入金追跡 |
| 7 | `vehicle_options` | `20260407000007_create_vehicle_options.sql` | オプションマスタ（Power Gate等） |
| 8 | `option_premiums` | `20260407000008_create_option_premiums.sql` | オプション別プレミアム率 |
| 9 | `defaults` | `20260407000009_create_defaults.sql` | デフォルト案件管理 |
| 10 | `default_events` | `20260407000010_create_default_events.sql` | デフォルトイベントタイムライン |
| 11 | `liquidation_records` | `20260407000011_create_liquidation_records.sql` | 清算記録 |
| 12 | `international_markets` | `20260407000012_create_international_markets.sql` | 海外市場マスタ |
| 13 | `yield_distributions` | `20260407000013_create_yield_distributions.sql` | 利回り分配記録 |
| 14 | `risk_metrics` | `20260407000014_create_risk_metrics.sql` | リスク指標スナップショット |

#### 主要テーブルのスキーマ設計

```sql
-- funds: ファンド（SPC）管理
CREATE TABLE public.funds (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name            text NOT NULL,
  fund_code       text NOT NULL UNIQUE,
  fund_type       text NOT NULL DEFAULT 'spc'
                  CHECK (fund_type IN ('spc', 'gk_tk', 'tmi')),
  target_aum_yen  bigint,          -- 目標運用資産総額
  current_aum_yen bigint DEFAULT 0, -- 現在運用資産総額
  nav_yen         bigint DEFAULT 0, -- 純資産価値
  nav_ratio       numeric(6,4),     -- NAV比率（> 0.60必須）
  status          text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('preparing', 'active', 'closed', 'liquidating')),
  inception_date  date,
  manager_user_id uuid REFERENCES public.users(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- fund_investors: 投資家配分
CREATE TABLE public.fund_investors (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id         uuid NOT NULL REFERENCES public.funds(id),
  user_id         uuid NOT NULL REFERENCES public.users(id),
  investment_yen  bigint NOT NULL,
  ownership_ratio numeric(8,6) NOT NULL, -- 持分比率
  status          text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('committed', 'active', 'redeemed')),
  invested_at     timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_fund_investor UNIQUE (fund_id, user_id)
);

-- fund_assets: ファンド保有車両
CREATE TABLE public.fund_assets (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id             uuid NOT NULL REFERENCES public.funds(id),
  vehicle_id          uuid REFERENCES public.vehicles(id),
  simulation_id       uuid REFERENCES public.simulations(id),
  lease_contract_id   uuid, -- FK追加後に設定
  purchase_price_yen  bigint NOT NULL,
  b2b_wholesale_yen   bigint NOT NULL,
  ltv_ratio           numeric(6,4) NOT NULL,
  current_value_yen   bigint,
  option_premium_yen  bigint DEFAULT 0,
  status              text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('acquired', 'active', 'defaulted', 'liquidated', 'disposed')),
  acquired_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- lease_contracts: リース契約
CREATE TABLE public.lease_contracts (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_asset_id         uuid NOT NULL REFERENCES public.fund_assets(id),
  lessee_name           text NOT NULL,
  lessee_company_id     text,
  contract_number       text NOT NULL UNIQUE,
  start_date            date NOT NULL,
  end_date              date NOT NULL,
  term_months           int NOT NULL,
  monthly_fee_yen       bigint NOT NULL,
  residual_value_yen    bigint,
  security_deposit_yen  bigint DEFAULT 0,
  status                text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('draft', 'active', 'overdue', 'defaulted', 'terminated', 'completed')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- lease_payments: 支払い追跡
CREATE TABLE public.lease_payments (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lease_contract_id   uuid NOT NULL REFERENCES public.lease_contracts(id),
  payment_month       int NOT NULL,       -- 1-based月番号
  due_date            date NOT NULL,
  amount_due_yen      bigint NOT NULL,
  amount_paid_yen     bigint DEFAULT 0,
  paid_at             timestamptz,
  status              text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'paid', 'partial', 'overdue', 'waived')),
  days_overdue        int DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- defaults: デフォルト案件
CREATE TABLE public.defaults (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lease_contract_id   uuid NOT NULL REFERENCES public.lease_contracts(id),
  fund_asset_id       uuid NOT NULL REFERENCES public.fund_assets(id),
  default_date        date NOT NULL,       -- T+0
  current_phase       text NOT NULL DEFAULT 't0_detection'
                      CHECK (current_phase IN ('t0_detection', 't1_recovery', 't3_repossession', 't10_liquidation', 'resolved')),
  total_outstanding_yen bigint,
  recovery_amount_yen   bigint DEFAULT 0,
  loss_amount_yen       bigint DEFAULT 0,
  status              text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'resolved', 'written_off')),
  resolved_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- default_events: デフォルトタイムラインイベント
CREATE TABLE public.default_events (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  default_id      uuid NOT NULL REFERENCES public.defaults(id),
  event_type      text NOT NULL
                  CHECK (event_type IN ('detection', 'notice_sent', 'contact_attempt', 'repossession_order', 'vehicle_recovered', 'liquidation_started', 'liquidation_completed', 'write_off')),
  event_date      timestamptz NOT NULL DEFAULT now(),
  description     text,
  performed_by    uuid REFERENCES public.users(id),
  metadata        jsonb DEFAULT '{}',
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- liquidation_records: 清算記録
CREATE TABLE public.liquidation_records (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  default_id            uuid REFERENCES public.defaults(id),
  fund_asset_id         uuid NOT NULL REFERENCES public.fund_assets(id),
  liquidation_type      text NOT NULL
                        CHECK (liquidation_type IN ('domestic_auction', 'domestic_direct', 'international', 'scrap')),
  target_market_id      uuid REFERENCES public.international_markets(id),
  asking_price_yen      bigint,
  sold_price_yen        bigint,
  liquidation_cost_yen  bigint DEFAULT 0,
  net_recovery_yen      bigint,
  status                text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'listed', 'sold', 'cancelled')),
  listed_at             timestamptz,
  sold_at               timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- international_markets: 海外市場マスタ
CREATE TABLE public.international_markets (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  country_code    text NOT NULL,   -- ISO 3166-1
  country_name    text NOT NULL,
  market_name     text NOT NULL,
  currency_code   text NOT NULL DEFAULT 'USD',
  avg_recovery_rate numeric(6,4), -- 平均回収率
  shipping_cost_yen bigint,
  is_active       boolean DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
```

---

## 3. 計算エンジン変更一覧

### 3.1 `app/core/pricing.py` — PricingEngine の変更点

#### (A) LTV 60%ルールの組み込み

**変更箇所**: `PricingEngine.DEFAULT_PARAMS`（L38-69）

```python
# 追加パラメータ
"ltv_cap": 0.60,                    # LTV上限（B2B wholesale基準）
"valuation_base": "b2b_wholesale",  # 価格算出ベース
"retail_reference_only": True,      # リテール価格は参考値のみ
```

**変更箇所**: `PricingEngine.calculate()` メソッド（L197-385）

- L250-259: `auction_prices` / `retail_prices` の分類ロジックに `b2b_wholesale_prices` を追加
- L268: `calculate_base_market_price()` 呼び出しを `calculate_b2b_wholesale_price()` に変更
- L290-293: `calculate_max_purchase_price()` の結果に LTV 60% キャップを適用

```python
# 変更後のロジック（擬似コード）
b2b_wholesale = self.calculate_b2b_wholesale_price(b2b_prices, auction_prices, p)
max_purchase_price_raw = self.calculate_max_purchase_price(...)
ltv_cap = p.get("ltv_cap", 0.60)
max_purchase_price = min(max_purchase_price_raw, b2b_wholesale * ltv_cap)
```

**新規メソッド**: `PricingEngine.calculate_b2b_wholesale_price()`

```python
def calculate_b2b_wholesale_price(
    self,
    b2b_prices: list[float],
    auction_prices: list[float],
    params: dict,
) -> float:
    """B2B wholesale floorに基づくベース価格算出。
    リテール価格は使用しない。"""
```

#### (B) B2B wholesale価格ベースへの切替

**変更箇所**: `PricingEngine.calculate_base_market_price()`（L390-443）

- 現行: `auction_weight * auction_median + (1 - auction_weight) * retail_median`
- 変更後: B2B wholesaleデータが最優先。auction価格はB2B proxyとして使用。retail価格は完全排除

#### (C) Option-Adjusted Valuation の追加

**新規クラス**: `app/core/option_valuation.py`

```python
class OptionAdjustedValuator:
    """オプション装備に基づく車両価値調整"""

    OPTION_PREMIUMS: dict[str, dict] = {
        "power_gate": {"premium_rate": 0.08, "depreciation_rate": 0.12},
        "cold_storage": {"premium_rate": 0.15, "depreciation_rate": 0.18},
        "crane": {"premium_rate": 0.12, "depreciation_rate": 0.15},
        "tail_lift": {"premium_rate": 0.06, "depreciation_rate": 0.10},
    }

    def calculate_option_adjusted_value(
        self,
        base_value: float,
        options: list[dict],
        elapsed_months: int,
    ) -> dict:
        """オプション込みの調整後価値を算出"""

    def calculate_option_premium(
        self,
        option_type: str,
        original_cost: float,
        elapsed_months: int,
    ) -> float:
        """個別オプションのプレミアム算出"""
```

**PricingEngine への統合**:

- `PricingEngine.calculate()` 内で `OptionAdjustedValuator` を呼び出し
- `SimulationInput` に `options: list[VehicleOption]` フィールドを追加

#### (D) ValueTransferEngine の新規追加

**新規ファイル**: `app/core/value_transfer.py`

```python
class ValueTransferEngine:
    """資産価値移転エンジニアリング — NAV > 60%維持を保証"""

    NAV_FLOOR: float = 0.60  # Net Fund Asset Valueの下限

    def calculate_nav(
        self,
        fund_id: str,
        assets: list[dict],
    ) -> dict:
        """ファンドのNAVを算出。
        Returns: nav_yen, nav_ratio, asset_breakdown"""

    def validate_acquisition(
        self,
        fund_id: str,
        proposed_purchase_price: float,
        b2b_wholesale_value: float,
        current_nav: dict,
    ) -> dict:
        """新規取得がNAV > 60%を維持できるか検証。
        Returns: is_valid, projected_nav_ratio, max_allowable_price"""

    def recalculate_nav_after_default(
        self,
        fund_id: str,
        defaulted_asset_value: float,
        recovery_estimate: float,
    ) -> dict:
        """デフォルト発生後のNAV再計算"""

    def generate_nav_report(
        self,
        fund_id: str,
        as_of_date: str,
    ) -> dict:
        """NAVレポート生成"""
```

### 3.2 `app/core/residual_value.py` — ResidualValueCalculator の変更点

**変更箇所**: `ResidualValueCalculator.predict()`（L282-404）

- オプション装備による残価への影響を加味
- B2B wholesale基準でのresidual value floor追加
- `market_data` の `median_price` をB2B wholesaleベースに変更

```python
# 追加パラメータ
def predict(
    self,
    purchase_price: float,
    category: str,
    body_type: str,
    elapsed_months: int,
    mileage: int,
    market_data: Optional[dict[str, Any]] = None,
    options: Optional[list[dict]] = None,         # 新規追加
    b2b_wholesale_floor: Optional[float] = None,  # 新規追加
) -> dict[str, Any]:
```

### 3.3 `app/core/market_analysis.py` — MarketAnalyzer の変更点

**新規メソッド追加**:

```python
def separate_price_tiers(
    self, vehicles: list[dict]
) -> dict[str, list[float]]:
    """価格データをB2B wholesale / auction / retailに3層分類"""

def calculate_b2b_wholesale_statistics(
    self, prices: list[float]
) -> dict[str, Any]:
    """B2B wholesale価格の統計サマリ"""
```

---

## 4. APIエンドポイント追加一覧

### 4.1 既存エンドポイントの変更

| エンドポイント | ファイル | 変更内容 |
|---------------|---------|---------|
| `POST /api/v1/simulations` | `app/api/simulation.py` L306-370 | `calculate_simulation()` にLTV/B2B wholesaleパラメータを渡す |
| `POST /api/v1/simulations/calculate` | `app/api/simulation.py` L619-657 | 同上 |
| `GET /api/v1/market-prices` | `app/api/market_prices.py` | `price_type` フィルタ追加 |

### 4.2 新規APIルーター・エンドポイント

#### ファンド管理: `app/api/funds.py`

| メソッド | パス | 用途 |
|---------|------|------|
| `POST` | `/api/v1/funds` | ファンド新規作成 |
| `GET` | `/api/v1/funds` | ファンド一覧（ページネーション） |
| `GET` | `/api/v1/funds/{fund_id}` | ファンド詳細 |
| `PUT` | `/api/v1/funds/{fund_id}` | ファンド更新 |
| `GET` | `/api/v1/funds/{fund_id}/nav` | NAV算出・取得 |
| `GET` | `/api/v1/funds/{fund_id}/nav/history` | NAV推移履歴 |
| `GET` | `/api/v1/funds/{fund_id}/assets` | ファンド保有資産一覧 |
| `POST` | `/api/v1/funds/{fund_id}/assets` | 資産追加（LTV検証込み） |
| `GET` | `/api/v1/funds/{fund_id}/investors` | 投資家一覧 |
| `POST` | `/api/v1/funds/{fund_id}/investors` | 投資家追加 |
| `POST` | `/api/v1/funds/{fund_id}/distributions` | 利回り分配実行 |

#### リース契約管理: `app/api/lease_contracts.py`

| メソッド | パス | 用途 |
|---------|------|------|
| `POST` | `/api/v1/lease-contracts` | リース契約作成 |
| `GET` | `/api/v1/lease-contracts` | 契約一覧 |
| `GET` | `/api/v1/lease-contracts/{contract_id}` | 契約詳細 |
| `PUT` | `/api/v1/lease-contracts/{contract_id}` | 契約更新 |
| `GET` | `/api/v1/lease-contracts/{contract_id}/payments` | 支払い一覧 |
| `POST` | `/api/v1/lease-contracts/{contract_id}/payments` | 入金記録 |
| `GET` | `/api/v1/lease-contracts/{contract_id}/payments/overdue` | 延滞一覧 |

#### デフォルト管理: `app/api/defaults.py`

| メソッド | パス | 用途 |
|---------|------|------|
| `POST` | `/api/v1/defaults` | デフォルト案件登録 |
| `GET` | `/api/v1/defaults` | デフォルト一覧 |
| `GET` | `/api/v1/defaults/{default_id}` | デフォルト詳細 |
| `POST` | `/api/v1/defaults/{default_id}/events` | イベント追加（フェーズ遷移） |
| `PUT` | `/api/v1/defaults/{default_id}/phase` | フェーズ更新 |
| `POST` | `/api/v1/defaults/{default_id}/resolve` | 解決処理 |

#### 清算管理: `app/api/liquidation.py`

| メソッド | パス | 用途 |
|---------|------|------|
| `POST` | `/api/v1/liquidations` | 清算案件作成 |
| `GET` | `/api/v1/liquidations` | 清算一覧 |
| `GET` | `/api/v1/liquidations/{liquidation_id}` | 清算詳細 |
| `PUT` | `/api/v1/liquidations/{liquidation_id}` | 清算更新（売却記録等） |
| `GET` | `/api/v1/liquidations/markets` | 海外市場マスタ一覧 |
| `POST` | `/api/v1/liquidations/{liquidation_id}/route` | 市場ルーティング決定 |

#### 投資家向け: `app/api/investor.py`

| メソッド | パス | 用途 |
|---------|------|------|
| `GET` | `/api/v1/investor/portfolio` | ポートフォリオサマリ |
| `GET` | `/api/v1/investor/funds` | 出資ファンド一覧 |
| `GET` | `/api/v1/investor/funds/{fund_id}/performance` | ファンドパフォーマンス |
| `GET` | `/api/v1/investor/distributions` | 分配金履歴 |
| `GET` | `/api/v1/investor/risk` | リスク指標一覧 |
| `GET` | `/api/v1/investor/reports` | レポート一覧 |

---

## 5. 画面追加一覧

### 5.1 既存画面の変更

| 画面 | テンプレートファイル | 変更内容 |
|------|-------------------|---------|
| シミュレーション入力 | `app/templates/pages/simulation.html` | オプション装備選択UI追加、LTV表示追加、B2B wholesale価格入力フィールド追加 |
| シミュレーション結果 | `app/templates/pages/simulation_result.html` | LTV比率表示、B2B wholesale基準表示、NAV影響表示を追加 |
| ダッシュボード | `app/templates/pages/dashboard.html` | ファンドサマリカード、アラート（延滞・デフォルト）表示を追加 |

### 5.2 新規画面一覧

| # | 画面名 | テンプレートファイル | ページルート（`app/api/pages.py`） | 主要機能 |
|---|--------|-------------------|-----------------------------------|---------|
| 1 | ファンド一覧 | `app/templates/pages/fund_list.html` | `GET /funds` | ファンド一覧、NAVサマリ、ステータスフィルタ |
| 2 | ファンド詳細 | `app/templates/pages/fund_detail.html` | `GET /funds/{fund_id}` | 保有資産一覧、NAV推移チャート、投資家一覧 |
| 3 | ファンド作成/編集 | `app/templates/pages/fund_form.html` | `GET /funds/new` | ファンド情報入力フォーム |
| 4 | リース契約一覧 | `app/templates/pages/lease_list.html` | `GET /lease-contracts` | 契約一覧、ステータスフィルタ、延滞アラート |
| 5 | リース契約詳細 | `app/templates/pages/lease_detail.html` | `GET /lease-contracts/{id}` | 支払いスケジュール、入金記録、延滞状況 |
| 6 | リース入金管理 | `app/templates/pages/lease_payment.html` | `GET /lease-contracts/{id}/payments` | 入金記録入力、一括消込 |
| 7 | 投資家ダッシュボード | `app/templates/pages/investor_dashboard.html` | `GET /investor` | ポートフォリオサマリ、NAV推移、分配金履歴 |
| 8 | 投資家ファンド詳細 | `app/templates/pages/investor_fund.html` | `GET /investor/funds/{fund_id}` | パフォーマンス、利回り、リスク指標 |
| 9 | デフォルト管理一覧 | `app/templates/pages/default_list.html` | `GET /defaults` | デフォルト案件一覧、フェーズ別フィルタ |
| 10 | デフォルト詳細 | `app/templates/pages/default_detail.html` | `GET /defaults/{id}` | タイムライン表示、イベント記録 |
| 11 | 清算管理一覧 | `app/templates/pages/liquidation_list.html` | `GET /liquidations` | 清算案件一覧、市場別集計 |
| 12 | 清算詳細 | `app/templates/pages/liquidation_detail.html` | `GET /liquidations/{id}` | 清算進捗、回収額、コスト |

---

## 6. 実装フェーズ計画

### Phase 2A: LTV/Valuation Stack改修 + Fund/Contract管理（2週間）

**Week 1: 計算エンジン改修 + DB拡張**

| 日 | タスク | ファイル |
|----|--------|---------|
| Day 1-2 | DB マイグレーション作成（funds, fund_investors, fund_assets, lease_contracts, lease_payments） | `supabase/migrations/20260407000001-000008_*.sql` |
| Day 2-3 | `PricingEngine` LTV 60%ルール組込み、`calculate_b2b_wholesale_price()` 新規追加 | `app/core/pricing.py` |
| Day 3-4 | `OptionAdjustedValuator` 新規実装 | `app/core/option_valuation.py` |
| Day 4-5 | `ValueTransferEngine` 新規実装（NAV計算） | `app/core/value_transfer.py` |
| Day 5 | `ResidualValueCalculator.predict()` 拡張 | `app/core/residual_value.py` |

**Week 2: API + 画面**

| 日 | タスク | ファイル |
|----|--------|---------|
| Day 6-7 | Pydanticモデル追加（Fund, LeaseContract, FundAsset） | `app/models/fund.py`, `app/models/lease.py` |
| Day 7-8 | リポジトリ追加 | `app/db/repositories/fund_repo.py`, `app/db/repositories/lease_repo.py` |
| Day 8-9 | APIルーター追加（funds, lease-contracts） | `app/api/funds.py`, `app/api/lease_contracts.py` |
| Day 9-10 | 画面追加（fund_list, fund_detail, lease_list, lease_detail） | `app/templates/pages/fund_*.html`, `app/templates/pages/lease_*.html` |
| Day 10 | 既存simulation画面のLTV/オプション対応改修 | `app/templates/pages/simulation.html`, `simulation_result.html` |

### Phase 2B: Default/Exit + Liquidation（2週間）

**Week 3: デフォルトワークフロー**

| 日 | タスク | ファイル |
|----|--------|---------|
| Day 11-12 | DB マイグレーション（defaults, default_events, liquidation_records, international_markets） | `supabase/migrations/20260407000009-000012_*.sql` |
| Day 12-13 | デフォルト検知エンジン（lease_payments延滞からの自動検知） | `app/core/default_detection.py` |
| Day 13-14 | デフォルトワークフローエンジン（T+0→T+1→T+3→T+10フェーズ管理） | `app/core/default_workflow.py` |
| Day 14-15 | Pydanticモデル + リポジトリ追加 | `app/models/default.py`, `app/db/repositories/default_repo.py` |

**Week 4: 清算 + 統合**

| 日 | タスク | ファイル |
|----|--------|---------|
| Day 16-17 | 清算ルーティングエンジン（国内/海外市場選択ロジック） | `app/core/liquidation_router.py` |
| Day 17-18 | APIルーター追加（defaults, liquidation） | `app/api/defaults.py`, `app/api/liquidation.py` |
| Day 18-19 | 画面追加（default_list, default_detail, liquidation_list, liquidation_detail） | `app/templates/pages/default_*.html`, `app/templates/pages/liquidation_*.html` |
| Day 19-20 | 延滞アラート通知機能、ダッシュボードへのアラート統合 | `app/core/notifications.py`, `app/templates/pages/dashboard.html` |

### Phase 2C: Investor Dashboard + Reports（2週間）

**Week 5: 投資家機能**

| 日 | タスク | ファイル |
|----|--------|---------|
| Day 21-22 | 投資家ロール・認可強化 | `app/dependencies.py`, `app/api/auth.py` |
| Day 22-23 | 投資家APIルーター | `app/api/investor.py` |
| Day 23-24 | 投資家ダッシュボード画面 | `app/templates/pages/investor_dashboard.html`, `investor_fund.html` |
| Day 24-25 | NAV推移チャート（Chart.js統合） | `static/js/nav_chart.js` |

**Week 6: レポート + テスト**

| 日 | タスク | ファイル |
|----|--------|---------|
| Day 26-27 | レポート生成エンジン（NAVレポート、リスクレポート） | `app/core/reporting.py` |
| Day 27-28 | yield_distributions, risk_metrics テーブル + API | `app/api/funds.py` に追加 |
| Day 28-29 | 全フェーズ統合テスト | `tests/unit/test_ltv_pricing.py`, `tests/unit/test_value_transfer.py`, `tests/integration/test_api_funds.py`, etc. |
| Day 30 | CI/CD更新、Vercelデプロイ確認 | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |

### Phase 3: Telemetry + ESG（将来）

| タスク | 概要 |
|--------|------|
| 車両テレメトリ連携 | GPS/OBDデータ取得API、`vehicle_telemetry`テーブル追加 |
| 動的価格設定 | リアルタイム市場データに基づく`DynamicPricingEngine` |
| ESG対応 | ESGスコアリングモデル、EV転換シミュレーション |

---

## 7. 既存コードの具体的変更箇所

### 7.1 `app/core/pricing.py`

| 行番号 | メソッド/箇所 | 変更内容 |
|--------|-------------|---------|
| L38-69 | `DEFAULT_PARAMS` | `ltv_cap: 0.60`, `valuation_base: "b2b_wholesale"`, `retail_reference_only: True` を追加 |
| L197-249 | `calculate()` 冒頭 | `b2b_wholesale_prices` リストの初期化追加 |
| L250-259 | `calculate()` 市場データ分類 | `price_type` に基づく3層分類（b2b/auction/retail）へ変更 |
| L268 | `calculate_base_market_price()` 呼出し | `calculate_b2b_wholesale_price()` に変更 |
| L290-293 | `calculate_max_purchase_price()` 後 | `min(max_purchase_price, b2b_wholesale * ltv_cap)` のキャップ追加 |
| L371-385 | `calculate()` return dict | `ltv_ratio`, `b2b_wholesale_price`, `option_adjusted_value` キーを追加 |
| L390-443 | `calculate_base_market_price()` | retail価格を排除し、B2B wholesale + auction のみのロジックに変更 |
| 新規 | `calculate_b2b_wholesale_price()` | B2B wholesaleフロアベースの価格算出メソッド追加 |
| 新規 | `apply_option_adjustments()` | `OptionAdjustedValuator`との連携メソッド追加 |

### 7.2 `app/core/residual_value.py`

| 行番号 | メソッド/箇所 | 変更内容 |
|--------|-------------|---------|
| L282-290 | `predict()` シグネチャ | `options`, `b2b_wholesale_floor` パラメータ追加 |
| L362-368 | `predict()` theoretical_value算出後 | オプション価値の減価を加味 |
| L371-404 | `predict()` return前 | `b2b_wholesale_floor` による残価下限設定 |

### 7.3 `app/core/market_analysis.py`

| 行番号 | メソッド/箇所 | 変更内容 |
|--------|-------------|---------|
| 新規 | `separate_price_tiers()` | B2B/auction/retailの3層分類メソッド追加 |
| 新規 | `calculate_b2b_wholesale_statistics()` | B2B wholesale価格専用の統計サマリ |
| L376-397 | `calculate_deviation_rate()` | B2B wholesale基準のdeviation計算に変更 |

### 7.4 `app/models/simulation.py`

| 行番号 | クラス | 変更内容 |
|--------|--------|---------|
| L10-78 | `SimulationInput` | `options: Optional[list[VehicleOptionInput]]`、`b2b_wholesale_price: Optional[int]`、`fund_id: Optional[UUID]` フィールド追加 |
| L113-167 | `SimulationResult` | `ltv_ratio: float`、`b2b_wholesale_price: int`、`option_adjusted_value: int`、`nav_impact: Optional[dict]` フィールド追加 |

### 7.5 新規Pydanticモデル

| ファイル | クラス | 用途 |
|---------|--------|------|
| `app/models/fund.py` | `FundCreate`, `FundResponse`, `FundAssetCreate`, `FundAssetResponse`, `FundInvestorCreate`, `FundInvestorResponse`, `NAVResponse`, `YieldDistributionCreate` | ファンド関連モデル |
| `app/models/lease.py` | `LeaseContractCreate`, `LeaseContractResponse`, `LeasePaymentCreate`, `LeasePaymentResponse` | リース契約関連モデル |
| `app/models/default.py` | `DefaultCreate`, `DefaultResponse`, `DefaultEventCreate`, `DefaultEventResponse` | デフォルト関連モデル |
| `app/models/liquidation.py` | `LiquidationCreate`, `LiquidationResponse`, `InternationalMarketResponse` | 清算関連モデル |
| `app/models/investor.py` | `PortfolioSummary`, `FundPerformance`, `RiskMetrics` | 投資家向けレスポンスモデル |
| `app/models/option.py` | `VehicleOptionInput`, `VehicleOptionResponse`, `OptionPremiumResponse` | オプション関連モデル |

### 7.6 新規リポジトリ

| ファイル | クラス | 用途 |
|---------|--------|------|
| `app/db/repositories/fund_repo.py` | `FundRepository` | funds, fund_investors, fund_assets, fund_nav_history CRUD |
| `app/db/repositories/lease_repo.py` | `LeaseRepository` | lease_contracts, lease_payments CRUD + 延滞検出クエリ |
| `app/db/repositories/default_repo.py` | `DefaultRepository` | defaults, default_events CRUD + フェーズ遷移 |
| `app/db/repositories/liquidation_repo.py` | `LiquidationRepository` | liquidation_records, international_markets CRUD |

### 7.7 新規コアエンジン

| ファイル | クラス | 用途 |
|---------|--------|------|
| `app/core/option_valuation.py` | `OptionAdjustedValuator` | オプション調整価値算出 |
| `app/core/value_transfer.py` | `ValueTransferEngine` | NAV計算、資産価値移転検証 |
| `app/core/default_detection.py` | `DefaultDetector` | 延滞からのデフォルト自動検知 |
| `app/core/default_workflow.py` | `DefaultWorkflowEngine` | T+0→T+10フェーズ管理 |
| `app/core/liquidation_router.py` | `LiquidationRouter` | 国内/海外市場ルーティング |
| `app/core/reporting.py` | `ReportGenerator` | NAV/リスク/パフォーマンスレポート生成 |
| `app/core/notifications.py` | `NotificationService` | 延滞・デフォルトアラート通知 |

### 7.8 `app/api/pages.py` — ページルート追加

```python
# 追加ルート（app/api/pages.py L150以降に追加）
@router.get("/funds")                         # ファンド一覧
@router.get("/funds/new")                     # ファンド作成
@router.get("/funds/{fund_id}")               # ファンド詳細
@router.get("/lease-contracts")               # リース契約一覧
@router.get("/lease-contracts/{contract_id}") # リース契約詳細
@router.get("/investor")                      # 投資家ダッシュボード
@router.get("/investor/funds/{fund_id}")      # 投資家ファンド詳細
@router.get("/defaults")                      # デフォルト一覧
@router.get("/defaults/{default_id}")         # デフォルト詳細
@router.get("/liquidations")                  # 清算一覧
@router.get("/liquidations/{liquidation_id}") # 清算詳細
```

### 7.9 `app/main.py` — ルーター登録

```python
# 追加ルーター登録
from app.api.funds import router as funds_router
from app.api.lease_contracts import router as lease_router
from app.api.defaults import router as defaults_router
from app.api.liquidation import router as liquidation_router
from app.api.investor import router as investor_router

app.include_router(funds_router)
app.include_router(lease_router)
app.include_router(defaults_router)
app.include_router(liquidation_router)
app.include_router(investor_router)
```

### 7.10 `app/dependencies.py` — 認可強化

```python
# 追加: ロールベースアクセス制御
def require_role(*allowed_roles: str):
    """指定ロールのいずれかを持つユーザーのみ許可するDependency"""

def get_fund_manager(current_user = Depends(get_current_user)):
    """fund_manager または admin ロールを要求"""

def get_investor_user(current_user = Depends(get_current_user)):
    """investor ロールを要求"""
```

### 7.11 テスト追加一覧

| ファイル | テスト数（見込み） | 内容 |
|---------|------------------|------|
| `tests/unit/test_ltv_pricing.py` | ~20 | LTV 60%ルール、B2B wholesale計算 |
| `tests/unit/test_option_valuation.py` | ~15 | オプション調整価値 |
| `tests/unit/test_value_transfer.py` | ~15 | NAV計算、取得検証 |
| `tests/unit/test_default_detection.py` | ~10 | 延滞検知ロジック |
| `tests/unit/test_default_workflow.py` | ~12 | フェーズ遷移 |
| `tests/unit/test_liquidation_router.py` | ~10 | 市場ルーティング |
| `tests/integration/test_api_funds.py` | ~20 | ファンドAPI CRUD |
| `tests/integration/test_api_lease.py` | ~18 | リースAPI CRUD + 入金 |
| `tests/integration/test_api_defaults.py` | ~15 | デフォルトAPI |
| `tests/integration/test_api_liquidation.py` | ~12 | 清算API |
| `tests/integration/test_api_investor.py` | ~10 | 投資家API |
| `tests/e2e/test_fund_workflow.py` | ~8 | ファンド作成→資産取得→リース→入金の一気通貫 |
| `tests/e2e/test_default_workflow.py` | ~8 | 延滞→デフォルト→清算の一気通貫 |

**テスト追加見込み: 約173件** （既存293件 + 新規173件 = 合計約466件）

### 7.12 CI/CD変更

| ファイル | 変更内容 |
|---------|---------|
| `.github/workflows/ci.yml` | 新規テストファイルのパス追加、DB マイグレーション実行ステップ追加 |
| `.github/workflows/deploy.yml` | マイグレーション自動実行ステップ追加 |
| `.github/workflows/scrape.yml` | B2B wholesale価格収集ジョブ追加 |

---

## 8. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| B2B wholesale価格データの不足 | LTV計算の精度低下 | auction価格をB2B proxyとして利用するフォールバックロジック実装 |
| NAV計算のリアルタイム性 | パフォーマンス劣化 | NAVスナップショットの定期バッチ計算 + キャッシュ |
| デフォルトワークフローの複雑性 | バグ混入リスク | ステートマシンパターン採用、フェーズ遷移の厳格なバリデーション |
| 既存テストへの影響 | `PricingEngine` 変更によるテスト破壊 | 既存テストの段階的マイグレーション、後方互換パラメータのデフォルト値維持 |
| Vercelデプロイサイズ | 新規コード追加によるサイズ増大 | 遅延インポート、不要依存の排除 |
