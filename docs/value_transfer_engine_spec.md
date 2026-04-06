# バリュートランスファーエンジン計算仕様書

**Value Transfer Engineering -- Neutralizes Physical Depreciation Risk**

| 項目 | 内容 |
|------|------|
| 文書バージョン | 1.0 |
| 作成日 | 2026-04-06 |
| 関連モジュール | `app.core.residual_value`, `app.core.pricing` |
| ステータス | 初版 |

---

## 目次

1. [概要](#1-概要)
2. [月次資産価値モデル](#2-月次資産価値モデル)
3. [60%ライン維持条件](#3-60ライン維持条件)
4. [バリューインバージョンポイント](#4-バリューインバージョンポイント)
5. [リース料の最適化](#5-リース料の最適化)
6. [シナリオ分析とストレステスト](#6-シナリオ分析とストレステスト)
7. [Python実装仕様](#7-python実装仕様)
8. [既存モジュールとの統合](#8-既存モジュールとの統合)

---

## 1. 概要

### 1.1 バリュートランスファーの原理

リースバックスキームでは、車両の物理的価値（Physical Vehicle Value）はリース期間を通じて減少するが、リース料の累積回収（Accumulated Cash Recovery）が同時に増加する。この「価値移転」により、ファンドの純資産価値（Net Fund Asset Value）はリース期間全体を通じて一定水準以上を維持する。

### 1.2 ピッチデックからの主要パラメータ（Page 4-5）

| パラメータ | Month 01 | Month 36 |
|-----------|----------|----------|
| Physical Asset Value (%) | 100% | ~30% |
| Accumulated Cash Recovery (%) | 0% | ~80% |
| Net Fund Asset Value (%) | 100% | ~110% (30+80) |
| 最低維持ライン | 60% | 60% |

- **LTV**: B2B卸売フロア価格の60%
- **ファンド資本投入額**: B2B卸売価格を大幅に下回る水準で設定

---

## 2. 月次資産価値モデル

### 2.1 基本定義

```
定義:
  P       = purchase_price        -- ファンド買取価格（円）
  W       = wholesale_floor       -- B2B卸売フロア価格（円）
  LTV     = 0.60                  -- Loan-to-Value比率
  T       = lease_term_months     -- リース期間（月数、標準36ヶ月）
  L       = monthly_lease_payment -- 月額リース料（円）
  r(t)    = depreciation_rate(t)  -- 月次t時点の減価率
```

### 2.2 ファンド投入額の制約

```
CONSTRAINT: P <= W × LTV

  P = W × 0.60  -- ファンド資本はB2B卸売フロアの60%以下で投入
```

これにより、取得時点で既に40%のバッファが存在する。

### 2.3 月次価値算出式

#### 2.3.1 物理的車両価値（Physical Vehicle Value）

```python
def physical_value(t: int) -> float:
    """月次tにおける車両の物理的市場価値。

    既存の ResidualValueCalculator.predict() を月次精度に拡張。
    category および body_type に応じた減価カーブを使用。
    """
    return purchase_price * depreciation_curve(t, category, body_type)
```

減価カーブ `depreciation_curve(t, category, body_type)` は以下で定義される:

```
depreciation_curve(t, category, body_type) =
    chassis_ratio × DB200_monthly(t, useful_life) +
    body_ratio × body_retention^(t / (12 × legal_life)) ×
    mileage_adjustment(t)

ここで:
  chassis_ratio = 0.70
  body_ratio    = 0.30
  DB200_monthly(t, n) = (1 - 2/n)^(t/12)  -- 200%定率法の月次近似
```

**物理的価値の比率（初期投入額に対する割合）:**

```
physical_value_ratio(t) = physical_value(t) / P
```

#### 2.3.2 累積キャッシュ回収（Accumulated Cash Recovery）

```python
def cash_recovery(t: int) -> float:
    """月次tまでの累積リース料回収額。"""
    return sum(monthly_lease_payment for i in range(1, t + 1))
    # = monthly_lease_payment × t  （均等払いの場合）
```

**キャッシュ回収比率（初期投入額に対する割合）:**

```
cash_recovery_ratio(t) = cash_recovery(t) / P
                        = (L × t) / P
```

#### 2.3.3 ファンド純資産価値（Net Fund Asset Value）

```python
def net_fund_asset_value(t: int) -> float:
    """月次tにおけるファンドの純資産価値。
    物理的車両価値 + 累積キャッシュ回収額。
    """
    return physical_value(t) + cash_recovery(t)
```

**純資産比率（初期投入額に対する割合）:**

```
net_fund_asset_ratio(t) = net_fund_asset_value(t) / P
                        = physical_value_ratio(t) + cash_recovery_ratio(t)
```

### 2.4 VALUE INVERSION MATRIX（月次推移例）

| 月 | physical_value_ratio | cash_recovery_ratio | net_fund_asset_ratio |
|----|---------------------|--------------------|--------------------|
| 0  | 1.000 | 0.000 | 1.000 |
| 6  | 0.880 | 0.133 | 1.013 |
| 12 | 0.750 | 0.267 | 1.017 |
| 18 | 0.620 | 0.400 | 1.020 |
| 24 | 0.500 | 0.533 | 1.033 |
| 30 | 0.390 | 0.667 | 1.057 |
| 36 | 0.300 | 0.800 | 1.100 |

> 注: 上記はピッチデック（Page 4）の数値に基づく参考値。実際の値は車種・カテゴリにより変動する。

---

## 3. 60%ライン維持条件

### 3.1 制約条件の定義

```
CONSTRAINT:
  net_fund_asset_ratio(t) >= 0.60   ∀ t ∈ [1, T]

すなわち:
  physical_value(t) + cash_recovery(t) >= 0.60 × P   ∀ t ∈ [1, T]
```

### 3.2 リース料の逆算式（最低リース料の導出）

60%ラインを維持するために必要な最低月額リース料を逆算する。

```
physical_value(t) + L × t >= 0.60 × P

∴ L >= (0.60 × P - physical_value(t)) / t   ∀ t ∈ [1, T]
```

全月で制約を満たすには:

```
L_min = max over t ∈ [1, T] of:
    max(0, (0.60 × P - physical_value(t)) / t)
```

**最小リース料の特定:**

減価カーブが凸（下に凸）の場合、制約が最も厳しくなるのは中間期（概ね t = T/2 付近）である。これはリース料の累積が未だ少なく、物理的価値が大幅に減少している時期に対応する。

```python
def calculate_minimum_lease_payment(purchase_price: float,
                                     depreciation_curve: callable,
                                     lease_term: int,
                                     floor_ratio: float = 0.60) -> float:
    """60%制約を全月で維持するための最低月額リース料を算出。"""
    L_min = 0.0
    for t in range(1, lease_term + 1):
        pv_t = purchase_price * depreciation_curve(t)
        required = (floor_ratio * purchase_price - pv_t) / t
        L_min = max(L_min, required)
    return max(L_min, 0.0)
```

### 3.3 制約最厳月（Critical Month）の特定

```python
def find_critical_month(purchase_price: float,
                        depreciation_curve: callable,
                        lease_term: int,
                        floor_ratio: float = 0.60) -> int:
    """60%ラインに対して最も制約が厳しい月を特定。"""
    worst_month = 1
    worst_shortfall = float('-inf')
    for t in range(1, lease_term + 1):
        pv_t = purchase_price * depreciation_curve(t)
        required_L = (floor_ratio * purchase_price - pv_t) / t
        if required_L > worst_shortfall:
            worst_shortfall = required_L
            worst_month = t
    return worst_month
```

### 3.4 アラートロジック

```python
def check_sixty_percent_constraint(
    purchase_price: float,
    monthly_lease_payment: float,
    depreciation_curve: callable,
    lease_term: int,
    floor_ratio: float = 0.60
) -> dict:
    """60%制約の充足状況をチェック。

    Returns:
        {
            "is_satisfied": bool,
            "violation_months": list[int],     -- 違反月のリスト
            "minimum_ratio": float,            -- 期間中の最小NAV比率
            "minimum_ratio_month": int,        -- 最小比率の月
            "margin_at_worst": float,          -- 最悪月での余裕率
        }
    """
```

**アラート発火条件:**

| レベル | 条件 | アクション |
|--------|------|----------|
| CRITICAL | `net_fund_asset_ratio(t) < 0.60` | 即座に通知。リース料再設定を要求 |
| WARNING | `net_fund_asset_ratio(t) < 0.65` | 注意喚起。モニタリング強化 |
| WATCH | `net_fund_asset_ratio(t) < 0.70` | 経過観察リストに追加 |

---

## 4. バリューインバージョンポイント

### 4.1 定義

**バリューインバージョンポイント（Value Inversion Point）** とは、累積キャッシュ回収額が物理的車両価値を上回る最初の月を指す。

```
inversion_point = min { t ∈ [1, T] : cash_recovery(t) > physical_value(t) }

すなわち:
  L × t > P × depreciation_curve(t)
```

### 4.2 算出ロジック

```python
def find_inversion_point(
    purchase_price: float,
    monthly_lease_payment: float,
    depreciation_curve: callable,
    lease_term: int
) -> int | None:
    """キャッシュ回収が物理価値を超える最初の月を返す。

    Returns:
        int: インバージョン月（1-based）。期間内に発生しない場合は None。
    """
    for t in range(1, lease_term + 1):
        cash = monthly_lease_payment * t
        physical = purchase_price * depreciation_curve(t)
        if cash > physical:
            return t
    return None
```

### 4.3 安全性指標としての解釈

```
inversion_safety_score = 1.0 - (inversion_point / lease_term)
```

| inversion_point | safety_score | 評価 |
|----------------|-------------|------|
| T/3 以前 (12ヶ月以前) | >= 0.67 | 極めて安全。早期に現金回収が支配的 |
| T/2 付近 (18ヶ月前後) | ~0.50 | 標準。適度なバランス |
| 2T/3 以降 (24ヶ月以降) | <= 0.33 | 要注意。物理的価値依存が長期間継続 |
| 期間内に未到達 | 0.00 | 危険。リース料が不十分 |

---

## 5. リース料の最適化

### 5.1 リース料の構成要素

```
monthly_lease_payment = capital_recovery + investor_return + risk_premium + operating_cost

ここで:
  capital_recovery  = 加速元本回収分
  investor_return   = 投資家目標利回り分
  risk_premium      = リスクプレミアム（信用リスク・流動性リスク）
  operating_cost    = 管理費・保険料・メンテナンス費
```

### 5.2 各構成要素の算出

#### 5.2.1 加速元本回収分

```
capital_recovery = (P - estimated_residual_value) / T

ここで:
  estimated_residual_value = P × residual_rate_at_term_end
```

#### 5.2.2 投資家目標利回り分

```
investor_return = P × (target_annual_yield / 12)

ここで:
  target_annual_yield: 年間目標利回り（例: 8% = 0.08）
```

#### 5.2.3 リスクプレミアム

```
risk_premium = P × (credit_spread + liquidity_premium) / 12

ここで:
  credit_spread     = 0.015  -- 既存PricingEngineのデフォルト値
  liquidity_premium = 0.005  -- 既存PricingEngineのデフォルト値
```

#### 5.2.4 運営コスト

```
operating_cost = (P × monthly_management_fee_rate) + fixed_monthly_admin_cost
                 + insurance_monthly + maintenance_monthly
```

### 5.3 最適化問題の定式化

```
目的関数:
  minimize L (月額リース料)

制約条件:
  (1) net_fund_asset_ratio(t) >= 0.60       ∀ t ∈ [1, T]
  (2) L >= capital_recovery + investor_return + risk_premium + operating_cost
  (3) effective_yield >= target_annual_yield
  (4) L <= market_competitive_ceiling       -- 市場競争力上限

最適解:
  L* = max(L_constraint_1, L_constraint_2)
```

```python
def optimize_lease_payment(
    purchase_price: float,
    wholesale_floor: float,
    depreciation_curve: callable,
    lease_term: int,
    target_annual_yield: float = 0.08,
    residual_rate: float = 0.10,
    floor_ratio: float = 0.60,
    credit_spread: float = 0.015,
    liquidity_premium: float = 0.005,
    monthly_mgmt_fee_rate: float = 0.002,
    fixed_admin_cost: float = 5000,
    insurance_monthly: float = 0,
    maintenance_monthly: float = 0,
) -> dict:
    """60%制約を維持しつつ最小のリース料を算出。

    Returns:
        {
            "optimal_lease_payment": float,
            "minimum_from_nav_constraint": float,
            "minimum_from_yield_requirement": float,
            "binding_constraint": str,  -- "nav_floor" | "yield"
            "inversion_point": int,
            "effective_yield": float,
            "margin_over_floor": float,
        }
    """
```

---

## 6. シナリオ分析とストレステスト

### 6.1 シナリオ定義

| パラメータ | 楽観シナリオ | 基本シナリオ | 悲観シナリオ |
|-----------|------------|------------|------------|
| 減価速度倍率 | 0.85 | 1.00 | 1.20 |
| リース料入金遅延 | 0ヶ月 | 0ヶ月 | 3ヶ月 |
| 中途解約確率 | 0% | 5% | 15% |
| 出口価格（対理論値） | +10% | ±0% | -15% |
| 市場価格変動 | +5% | ±0% | -10% |

### 6.2 シナリオ別NAV推移の算出

```python
def run_scenario_analysis(
    purchase_price: float,
    monthly_lease_payment: float,
    depreciation_curve: callable,
    lease_term: int,
    scenario: str = "base"  -- "optimistic" | "base" | "pessimistic"
) -> dict:
    """指定シナリオでのNAV推移を算出。

    Returns:
        {
            "scenario": str,
            "monthly_nav": list[dict],  -- 月次NAV明細
            "min_nav_ratio": float,
            "min_nav_month": int,
            "sixty_pct_satisfied": bool,
            "inversion_point": int | None,
            "terminal_nav_ratio": float,
        }
    """
```

### 6.3 ストレステスト仕様

#### 6.3.1 減価加速テスト

```
テスト名: STRESS_DEPRECIATION_ACCELERATED
条件: depreciation_curve(t) を 20% 加速
  stressed_curve(t) = depreciation_curve(t) × (1 - 0.20 × (t / T))

検証:
  net_fund_asset_ratio(t) >= 0.60   ∀ t ∈ [1, T]
```

#### 6.3.2 リース料遅延テスト

```
テスト名: STRESS_PAYMENT_DELAY
条件: リース料入金が3ヶ月遅延
  cash_recovery_stressed(t) = L × max(0, t - 3)

検証:
  net_fund_asset_ratio(t) >= 0.60   ∀ t ∈ [1, T]
```

#### 6.3.3 複合ストレステスト

```
テスト名: STRESS_COMBINED
条件: 減価20%加速 + リース料3ヶ月遅延 + 出口価格15%下落

検証:
  net_fund_asset_ratio(t) >= 0.50   ∀ t ∈ [1, T]
  （複合ストレスでは閾値を50%に緩和）
```

#### 6.3.4 ストレステスト結果フォーマット

```python
def run_stress_test(
    purchase_price: float,
    monthly_lease_payment: float,
    depreciation_curve: callable,
    lease_term: int,
    scenario: dict
) -> dict:
    """ストレステストを実行。

    scenario dict:
        {
            "name": str,
            "depreciation_multiplier": float,  -- 減価加速倍率 (例: 1.20)
            "payment_delay_months": int,        -- 入金遅延月数 (例: 3)
            "exit_price_shock": float,          -- 出口価格ショック (例: -0.15)
            "floor_ratio_override": float,      -- 閾値のオーバーライド (例: 0.50)
        }

    Returns:
        {
            "scenario_name": str,
            "passed": bool,
            "monthly_nav": list[dict],
            "min_nav_ratio": float,
            "min_nav_month": int,
            "violations": list[dict],  -- 違反月の詳細
            "margin_to_floor": float,  -- 最悪月での閾値との差分
        }
    """
```

---

## 7. Python実装仕様

### 7.1 クラス定義

```python
class ValueTransferEngine:
    """バリュートランスファーエンジン。

    物理的車両価値の減少をリース料の累積回収で相殺し、
    ファンドの純資産価値を常時60%以上に維持するための
    計算・検証・最適化エンジン。

    Attributes:
        purchase_price (float): ファンド買取価格（円）
        wholesale_floor (float): B2B卸売フロア価格（円）
        monthly_lease_payment (float): 月額リース料（円）
        lease_term_months (int): リース期間（月数）
        category (str): 車両カテゴリ（例: "普通貨物"）
        body_type (str): 架装タイプ（例: "ウイング"）
        residual_calculator (ResidualValueCalculator): 残価計算インスタンス
    """

    FLOOR_RATIO: float = 0.60
    LTV_RATIO: float = 0.60

    def __init__(
        self,
        purchase_price: float,
        wholesale_floor: float,
        monthly_lease_payment: float,
        lease_term_months: int,
        category: str,
        body_type: str,
        mileage_km: int = 0,
        market_data: dict | None = None,
    ) -> None: ...
```

### 7.2 メソッド一覧

```python
    # ------------------------------------------------------------------ #
    # 月次NAV算出
    # ------------------------------------------------------------------ #

    def calculate_monthly_nav(self, t: int) -> dict:
        """指定月のNAV明細を算出。

        Args:
            t: 月次（1-based、1 <= t <= lease_term_months）

        Returns:
            {
                "month": int,
                "physical_value": float,          -- 車両物理価値（円）
                "physical_value_ratio": float,    -- 初期投入額比（0-1）
                "cash_recovery": float,           -- 累積キャッシュ回収（円）
                "cash_recovery_ratio": float,     -- 初期投入額比（0-1）
                "net_fund_asset_value": float,    -- NAV（円）
                "net_fund_asset_ratio": float,    -- NAV比率（0-1+）
                "floor_margin": float,            -- 60%ラインとの差分
            }

        Raises:
            ValueError: t が範囲外の場合
        """

    def calculate_full_schedule(self) -> list[dict]:
        """全期間の月次NAVスケジュールを算出。

        Returns:
            list[dict]: 各月の calculate_monthly_nav() 結果のリスト
        """

    # ------------------------------------------------------------------ #
    # 制約チェック
    # ------------------------------------------------------------------ #

    def check_sixty_percent_constraint(self) -> dict:
        """60%制約の充足状況をチェック。

        Returns:
            {
                "is_satisfied": bool,
                "violation_months": list[int],
                "minimum_ratio": float,
                "minimum_ratio_month": int,
                "margin_at_worst": float,
                "alert_level": str,  -- "OK" | "WATCH" | "WARNING" | "CRITICAL"
            }
        """

    # ------------------------------------------------------------------ #
    # インバージョンポイント
    # ------------------------------------------------------------------ #

    def find_inversion_point(self) -> int | None:
        """キャッシュ回収が物理価値を超える最初の月を返す。

        Returns:
            int: インバージョン月（1-based）。未到達の場合は None。
        """

    def calculate_inversion_safety_score(self) -> float:
        """インバージョンポイントに基づく安全性スコア（0.0-1.0）。

        Returns:
            float: 1.0に近いほど安全。
        """

    # ------------------------------------------------------------------ #
    # リース料最適化
    # ------------------------------------------------------------------ #

    def optimize_lease_payment(
        self,
        target_annual_yield: float = 0.08,
        residual_rate: float = 0.10,
    ) -> dict:
        """60%制約を維持しつつ最小リース料を算出。

        Returns:
            {
                "optimal_lease_payment": float,
                "minimum_from_nav_constraint": float,
                "minimum_from_yield_requirement": float,
                "binding_constraint": str,
                "inversion_point_at_optimal": int | None,
                "effective_yield": float,
            }
        """

    def calculate_effective_yield(self, lease_payment: float | None = None) -> float:
        """実効利回り（年率）を算出。

        Args:
            lease_payment: 指定しない場合は self.monthly_lease_payment を使用

        Returns:
            float: 年間実効利回り（例: 0.082 = 8.2%）
        """

    # ------------------------------------------------------------------ #
    # シナリオ分析・ストレステスト
    # ------------------------------------------------------------------ #

    def run_scenario_analysis(
        self, scenario: str = "base"
    ) -> dict:
        """楽観・基本・悲観シナリオでのNAV推移を算出。

        Args:
            scenario: "optimistic" | "base" | "pessimistic"

        Returns:
            dict: シナリオ分析結果
        """

    def run_stress_test(self, scenario: dict) -> dict:
        """カスタムストレステストを実行。

        Args:
            scenario: ストレスシナリオ定義 dict

        Returns:
            dict: テスト結果（passed, violations, margin等）
        """

    def run_all_stress_tests(self) -> list[dict]:
        """標準ストレステストスイート（減価加速・遅延・複合）を一括実行。

        Returns:
            list[dict]: 各テストの結果リスト
        """

    # ------------------------------------------------------------------ #
    # 内部メソッド
    # ------------------------------------------------------------------ #

    def _depreciation_curve(self, t: int) -> float:
        """月次tにおける減価率（0-1）を返す。

        ResidualValueCalculator の declining_balance_200 および
        body_retention を月次精度で統合。

        Args:
            t: 月次（0-based or 1-based、内部で調整）

        Returns:
            float: 減価率。1.0 = 新車価値の100%、0.3 = 30%残存。
        """

    def _apply_stress_to_curve(
        self, t: int, depreciation_multiplier: float = 1.0
    ) -> float:
        """ストレス条件を適用した減価率を返す。"""

    def _calculate_cash_recovery(
        self, t: int, payment_delay_months: int = 0
    ) -> float:
        """遅延条件を考慮した累積キャッシュ回収額を返す。"""
```

### 7.3 使用例

```python
from app.core.value_transfer_engine import ValueTransferEngine

# エンジン初期化
engine = ValueTransferEngine(
    purchase_price=3_600_000,       # ファンド買取価格
    wholesale_floor=6_000_000,      # B2B卸売フロア（LTV 60%で取得）
    monthly_lease_payment=120_000,  # 月額リース料
    lease_term_months=36,
    category="普通貨物",
    body_type="ウイング",
    mileage_km=85_000,
)

# 月次NAV確認
nav_month_18 = engine.calculate_monthly_nav(18)
print(f"Month 18 NAV比率: {nav_month_18['net_fund_asset_ratio']:.1%}")
# => "Month 18 NAV比率: 102.0%"

# 60%制約チェック
constraint = engine.check_sixty_percent_constraint()
print(f"制約充足: {constraint['is_satisfied']}")
print(f"最小NAV比率: {constraint['minimum_ratio']:.1%} (月{constraint['minimum_ratio_month']})")
# => "制約充足: True"
# => "最小NAV比率: 95.3% (月6)"

# インバージョンポイント
inv = engine.find_inversion_point()
print(f"インバージョンポイント: 月{inv}")
# => "インバージョンポイント: 月20"

# リース料最適化
optimal = engine.optimize_lease_payment(target_annual_yield=0.08)
print(f"最適リース料: ¥{optimal['optimal_lease_payment']:,.0f}")
print(f"制約要因: {optimal['binding_constraint']}")
# => "最適リース料: ¥105,000"
# => "制約要因: yield"

# ストレステスト一括実行
stress_results = engine.run_all_stress_tests()
for result in stress_results:
    status = "PASS" if result["passed"] else "FAIL"
    print(f"[{status}] {result['scenario_name']}: "
          f"最小NAV={result['min_nav_ratio']:.1%}")
# => "[PASS] STRESS_DEPRECIATION_ACCELERATED: 最小NAV=82.1%"
# => "[PASS] STRESS_PAYMENT_DELAY: 最小NAV=71.5%"
# => "[PASS] STRESS_COMBINED: 最小NAV=58.3%"
```

---

## 8. 既存モジュールとの統合

### 8.1 依存関係

```
ValueTransferEngine
  ├── app.core.residual_value.ResidualValueCalculator
  │     ├── declining_balance_200()    -- シャーシ減価
  │     ├── _BODY_RETENTION            -- 架装価値残存率
  │     └── _mileage_adjustment_factor() -- 走行距離補正
  ├── app.core.pricing.PricingEngine
  │     └── DEFAULT_PARAMS             -- リスクプレミアム等のデフォルト値
  └── app.models.simulation
        ├── SimulationInput            -- 入力パラメータ型
        └── MonthlyScheduleItem        -- 月次明細型（拡張予定）
```

### 8.2 MonthlyScheduleItem の拡張

既存の `MonthlyScheduleItem` に以下のフィールドを追加する:

```python
class MonthlyScheduleItem(BaseModel):
    # 既存フィールド（省略）...

    # --- Value Transfer Engine 拡張フィールド ---
    physical_value: int = Field(
        ..., description="月次時点の車両物理価値（円）"
    )
    physical_value_ratio: float = Field(
        ..., description="初期投入額に対する物理価値比率"
    )
    cash_recovery_ratio: float = Field(
        ..., description="初期投入額に対するキャッシュ回収比率"
    )
    net_fund_asset_ratio: float = Field(
        ..., description="NAV比率（physical + cash / initial）"
    )
    floor_margin: float = Field(
        ..., description="60%ラインとの余裕率"
    )
```

### 8.3 PricingEngine との連携

`PricingEngine.run_simulation()` のパイプラインに ValueTransferEngine の検証を組み込む:

```
既存フロー:
  SimulationInput → PricingEngine → SimulationResult

拡張フロー:
  SimulationInput
    → PricingEngine (買取価格・リース料算出)
    → ValueTransferEngine (NAV検証・60%制約チェック)
    → SimulationResult (NAVメトリクス付加)
```

---

## 付録A: 数式一覧

| 記号 | 定義 | 単位 |
|------|------|------|
| P | ファンド買取価格 | 円 |
| W | B2B卸売フロア価格 | 円 |
| T | リース期間 | 月 |
| L | 月額リース料 | 円 |
| t | 経過月数 | 月 |
| PV(t) | physical_value(t) = P × d(t) | 円 |
| CR(t) | cash_recovery(t) = L × t | 円 |
| NAV(t) | PV(t) + CR(t) | 円 |
| d(t) | depreciation_curve(t) | 無次元 (0-1) |
| r(t) | NAV(t) / P = d(t) + (L×t)/P | 無次元 |
| L_min | max_{t} { (0.6P - PV(t)) / t } | 円 |
| t_inv | min { t : CR(t) > PV(t) } | 月 |

## 付録B: 配置先ファイルパス

```
app/core/value_transfer_engine.py    -- メインエンジンクラス
app/models/simulation.py             -- MonthlyScheduleItem 拡張
tests/unit/test_value_transfer.py    -- 単体テスト
docs/value_transfer_engine_spec.md   -- 本仕様書
```
