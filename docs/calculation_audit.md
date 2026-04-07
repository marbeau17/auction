# リースバック価格計算ロジック 監査報告書

**作成日:** 2026-04-06  
**対象コード:** `app/core/pricing.py`, `app/core/residual_value.py`, `app/core/market_analysis.py`, `app/api/simulation.py`  
**監査範囲:** 全計算関数の数式・パラメータ・前提条件の網羅的な記録

---

## 目次

1. [PricingEngine クラス (pricing.py)](#1-pricingengine-クラス)
2. [後方互換ラッパー関数 (pricing.py)](#2-後方互換ラッパー関数)
3. [calculate_simulation 非同期関数 (pricing.py)](#3-calculate_simulation-非同期関数)
4. [ResidualValueCalculator クラス (residual_value.py)](#4-residualvaluecalculator-クラス)
5. [MarketAnalyzer クラス (market_analysis.py)](#5-marketanalyzer-クラス)
6. [calculate_simulation_quick API (simulation.py)](#6-calculate_simulation_quick-api)
7. [二系統の計算ロジックの乖離分析](#7-二系統の計算ロジックの乖離分析)

---

## 1. PricingEngine クラス

**ファイル:** `app/core/pricing.py`, line 27

### デフォルトパラメータ (DEFAULT_PARAMS)

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `auction_weight` | 0.70 | オークション価格の加重比率 |
| `elevated_auction_weight` | 0.85 | 乖離大の場合のオークション加重比率 |
| `acceptable_deviation_threshold` | 0.15 | オークション/小売乖離の許容閾値 |
| `base_safety_margin` | 0.05 | 基本安全マージン |
| `volatility_premium` | 1.5 | ボラティリティに対するプレミアム係数 |
| `min_safety_margin` | 0.03 | 安全マージン下限 |
| `max_safety_margin` | 0.20 | 安全マージン上限 |
| `trend_floor` | 0.80 | トレンド係数下限 |
| `trend_ceiling` | 1.20 | トレンド係数上限 |
| `fund_cost_rate` | 0.020 | 資金調達コスト (年率) |
| `credit_spread` | 0.015 | 信用スプレッド (年率) |
| `liquidity_premium` | 0.005 | 流動性プレミアム (年率) |
| `monthly_management_fee_rate` | 0.002 | 月次管理手数料率 |
| `fixed_monthly_admin_cost` | 5,000 | 固定月次事務費 (円) |
| `profit_margin_rate` | 0.08 | 利益マージン率 |
| `target_annual_roi` | 0.08 | 目標年間ROI |
| `over_mileage_penalty_rate` | 0.30 | 超過走行ペナルティ率 |
| `under_mileage_bonus_rate` | 0.15 | 走行距離過少ボーナス率 |
| `mileage_adj_floor` | 0.70 | 走行距離調整係数下限 |
| `mileage_adj_ceiling` | 1.10 | 走行距離調整係数上限 |
| `early_termination_penalty_months` | 3 | 早期解約ペナルティ月数 |
| `forced_sale_discount` | 0.85 | 強制売却ディスカウント率 |

### カテゴリ別定数

**SAFETY_MARGINS_BY_CATEGORY:**
| カテゴリ | 安全マージン |
|---|---|
| SMALL | 0.05 |
| MEDIUM | 0.05 |
| LARGE | 0.07 |
| TRAILER_HEAD | 0.08 |
| TRAILER_CHASSIS | 0.06 |

**ANNUAL_STANDARD_MILEAGE (km/年):**
| カテゴリ | 標準走行距離 |
|---|---|
| SMALL | 30,000 |
| MEDIUM | 50,000 |
| LARGE | 80,000 |
| TRAILER_HEAD | 100,000 |

注意: `TRAILER_CHASSIS` は定義なし。`calculate_mileage_adjustment` ではデフォルト50,000が使用される。

**USEFUL_LIFE (年):**
| カテゴリ | 耐用年数 |
|---|---|
| SMALL | 7 |
| MEDIUM | 9 |
| LARGE | 10 |
| TRAILER_HEAD | 10 |
| TRAILER_CHASSIS | 12 |

**SALVAGE_RATIO:**
| カテゴリ | 残存率 |
|---|---|
| SMALL | 0.10 |
| MEDIUM | 0.08 |
| LARGE | 0.07 |
| TRAILER_HEAD | 0.06 |
| TRAILER_CHASSIS | 0.05 |

---

### 関数名: PricingEngine.calculate
**ファイル:** `app/core/pricing.py`, line 197
**シグネチャ:**
```python
def calculate(self, input_data: dict, market_data: list[dict] | None = None, params: dict | None = None) -> dict
```
**処理フロー:**
1. カテゴリ解決 (`_resolve_category`) と架装タイプ解決 (`_resolve_body_type`)
2. 登録年月から経過月数を算出: `elapsed_months = (now.year - reg_year) * 12 + (now.month - reg_month)`
3. 市場データを auction/retail に分離 (`source_site` に "auction" を含むかで判別)
4. 市場データがない場合、`acquisition_price` を auction/retail 両方のプロキシとして使用
5. `calculate_base_market_price` でベース市場価格算出
6. トレンド係数算出 (市場データの前半/後半に分割)
7. 安全マージン算出
8. `max_purchase_price = base_market_price * condition_factor * trend_factor * (1 - safety_margin)`
9. `recommended_purchase_price = min(max_purchase_price, book_value)` (book_value > 0 の場合)
10. 残価算出 (定額法)、`residual_rate` オーバーライドがあれば `recommended_price * residual_rate` を使用
11. 月額リース料算出 (`calculate_monthly_lease_payment`)
12. スケジュール生成、損益分岐点算出
13. 実効利回り: `((total_income - total_cost) / recommended_price) / (lease_term / 12)`
14. 市場乖離率: `(recommended_price - base_market_price) / base_market_price`
15. 総合判定

**計算式 (実効利回り):**
```
total_income = monthly_lease_fee * lease_term
total_cost = recommended_purchase_price - residual_value
effective_yield = ((total_income - total_cost) / recommended_purchase_price) / (lease_term / 12)
```

**問題点:**
- `condition_factor` は常に `1.0` にハードコードされており、車両状態による調整が機能していない
- トレンド係数の算出で市場データの前半/後半分割は時系列順が保証されていない (データの挿入順に依存)
- 市場データがない場合に `acquisition_price` を auction と retail の両方に入れることで、加重平均が意味をなさない

---

### 関数名: PricingEngine.calculate_base_market_price
**ファイル:** `app/core/pricing.py`, line 390
**シグネチャ:**
```python
def calculate_base_market_price(self, auction_prices: list[float], retail_prices: list[float], params: dict) -> float
```
**計算式:**
```
auction_median = median(auction_prices)
retail_median = median(retail_prices)
mean_of_medians = (auction_median + retail_median) / 2
deviation = |auction_median - retail_median| / mean_of_medians

if deviation > acceptable_deviation_threshold (0.15):
    w = elevated_auction_weight (0.85)
else:
    w = auction_weight (0.70)

base_market_price = w * auction_median + (1 - w) * retail_median
```
**特記:** オークションデータのみの場合は `median(auction)` をそのまま返却。小売のみの場合は `median(retail)` を返却。

---

### 関数名: PricingEngine.calculate_max_purchase_price
**ファイル:** `app/core/pricing.py`, line 448
**シグネチャ:**
```python
def calculate_max_purchase_price(self, base_market_price: float, condition_factor: float, trend_factor: float, safety_margin_rate: float) -> float
```
**計算式:**
```
max_price = base_market_price * condition_factor * trend_factor * (1.0 - safety_margin_rate)
```

---

### 関数名: PricingEngine.calculate_trend_factor
**ファイル:** `app/core/pricing.py`, line 489
**シグネチャ:**
```python
def calculate_trend_factor(self, recent_prices: list[float], baseline_prices: list[float], params: dict) -> float
```
**計算式:**
```
raw_factor = median(recent_prices) / median(baseline_prices)
trend_factor = clamp(raw_factor, trend_floor=0.80, trend_ceiling=1.20)
```

---

### 関数名: PricingEngine.calculate_safety_margin
**ファイル:** `app/core/pricing.py`, line 532
**シグネチャ:**
```python
def calculate_safety_margin(self, prices: list[float], category: str, params: dict) -> float
```
**計算式:**
```
cv = std(prices) / mean(prices)                    # 変動係数
dynamic = base_safety_margin(0.05) + cv * volatility_premium(1.5)
margin = clamp(dynamic, min_safety_margin=0.03, max_safety_margin=0.20)
```
**特記:** サンプル2未満の場合はカテゴリ別デフォルト値を使用。`_std` は `np.std` (母集団標準偏差, ddof=0) を使用。

**問題点:** 母集団標準偏差 (`ddof=0`) を使用しているが、サンプル標準偏差 (`ddof=1`) の方が少数サンプルには適切。`MarketAnalyzer.calculate_statistics` は `ddof=1` を使用しており、不一致がある。

---

### 関数名: PricingEngine.calculate_residual_value
**ファイル:** `app/core/pricing.py`, line 587
**シグネチャ:**
```python
def calculate_residual_value(self, purchase_price: float, elapsed_months: int, category: str, body_type: str, actual_mileage: int, method: str = "straight_line", params: dict | None = None) -> float
```
**計算式 (定額法, デフォルト):**
```
useful_life_years = USEFUL_LIFE[category]  # e.g. 10
salvage_value = purchase_price * SALVAGE_RATIO[category]  # e.g. 0.07
total_months = useful_life_years * 12
monthly_dep = (purchase_price - salvage_value) / total_months
chassis_value = max(purchase_price - monthly_dep * elapsed_months, salvage_value)
```
**計算式 (定率法):**
```
rate = 2.0 / useful_life_years
chassis_value = max(purchase_price * (1 - rate)^(elapsed_months/12), salvage_value)
```
**最終残価:**
```
body_factor = interpolate(BODY_DEPRECIATION_TABLES[body_type], elapsed_years)
mileage_adj = calculate_mileage_adjustment(...)
residual = max(chassis_value * body_factor * mileage_adj, 0.0)
```

**問題点:** `calculate` メソッドでは `method="straight_line"` がハードコードされており、定率法は選択できない。

---

### 関数名: PricingEngine.calculate_body_depreciation_factor
**ファイル:** `app/core/pricing.py`, line 669
**シグネチャ:**
```python
def calculate_body_depreciation_factor(self, body_type: str, elapsed_years: float) -> float
```
**計算式:** `BODY_DEPRECIATION_TABLES` テーブルから線形補間。テーブル定義なしの場合は `1.0` を返却。

**架装減価テーブル例 (WING):**
| 経過年 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 12 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 係数 | 1.00 | 0.92 | 0.85 | 0.78 | 0.72 | 0.66 | 0.60 | 0.55 | 0.50 | 0.45 | 0.40 | 0.32 | 0.22 |

---

### 関数名: PricingEngine.calculate_mileage_adjustment
**ファイル:** `app/core/pricing.py`, line 714
**シグネチャ:**
```python
def calculate_mileage_adjustment(self, actual_mileage: int, elapsed_years: float, category: str, params: dict) -> float
```
**計算式:**
```
expected_mileage = ANNUAL_STANDARD_MILEAGE[category] * elapsed_years
mileage_ratio = actual_mileage / expected_mileage
deviation = mileage_ratio - 1.0

if deviation > 0 (超過走行):
    factor = 1.0 - deviation * over_mileage_penalty_rate(0.30)
else (走行距離過少):
    factor = 1.0 - deviation * under_mileage_bonus_rate(0.15)
    # deviation < 0 なので、factor > 1.0 (ボーナス)

factor = clamp(factor, mileage_adj_floor=0.70, mileage_adj_ceiling=1.10)
```

---

### 関数名: PricingEngine.calculate_monthly_lease_payment
**ファイル:** `app/core/pricing.py`, line 775
**シグネチャ:**
```python
def calculate_monthly_lease_payment(self, purchase_price: float, residual_value: float, lease_term_months: int, params: dict) -> dict
```
**計算式:**
```
# 元本回収 (定額法)
principal_recovery = (purchase_price - residual_value) / lease_term_months

# 金利 (平均残高法)
annual_rate = fund_cost_rate(0.020) + credit_spread(0.015) + liquidity_premium(0.005) = 0.040
average_balance = (purchase_price + residual_value) / 2
interest_charge = average_balance * annual_rate / 12

# 管理費
management_fee = purchase_price * monthly_management_fee_rate(0.002) + fixed_monthly_admin_cost(5000)

# 利益マージン
subtotal = principal_recovery + interest_charge + management_fee
profit_margin = subtotal * profit_margin_rate(0.08)

# 月額リース料合計
total = subtotal + profit_margin
```

**戻り値:** `{principal_recovery, interest_charge, management_fee, profit_margin, total}`

---

### 関数名: PricingEngine.calculate_from_target_yield
**ファイル:** `app/core/pricing.py`, line 853
**シグネチャ:**
```python
def calculate_from_target_yield(self, purchase_price: float, residual_value: float, lease_term_months: int, target_yield: float) -> float
```
**計算式 (年金現価係数ベースのPMT計算):**
```
r = target_yield / 12
n = lease_term_months
PV_residual = residual_value / (1 + r)^n
net = purchase_price - PV_residual
PMT = net * r / (1 - (1 + r)^(-n))
```
**特記:** `r = 0` の場合: `PMT = (purchase_price - residual_value) / n`

**問題点:** この関数は `calculate` メソッドから呼ばれておらず、使用されていない。`calculate` は代わりにコスト積上げ方式の `calculate_monthly_lease_payment` を使用している。

---

### 関数名: PricingEngine.calculate_breakeven_month
**ファイル:** `app/core/pricing.py`, line 906
**シグネチャ:**
```python
def calculate_breakeven_month(self, purchase_price: float, monthly_payment: float, asset_values: list[float]) -> int | None
```
**計算式:**
```
月 m で損益分岐 = cumulative_income(m) >= purchase_price - asset_value(m)
# 1-based の月番号を返す。到達しない場合は None。
```

---

### 関数名: PricingEngine.calculate_monthly_schedule
**ファイル:** `app/core/pricing.py`, line 942
**シグネチャ:**
```python
def calculate_monthly_schedule(self, purchase_price: float, monthly_payment: float, lease_term_months: int, category: str, body_type: str, mileage: int, params: dict) -> list[dict]
```
**計算式 (各月 m):**
```
# 減価償却 (全耐用年数ベースの定額法)
total_dep = purchase_price - salvage_value
dep_expense = total_dep / (useful_life_years * 12)    # 月次一定
asset_value = max(purchase_price - dep_expense * m, salvage_value)

# 金融費用 (残高逓減法)
annual_rate = fund_cost_rate + credit_spread + liquidity_premium = 0.040
financing_cost = remaining_balance * (annual_rate / 12)

# 月次損益
monthly_profit = lease_income - dep_expense - financing_cost

# 残高更新
remaining_balance -= (lease_income - financing_cost)
remaining_balance = max(remaining_balance, 0)

# 早期解約損失
forced_sale_value = asset_value * forced_sale_discount(0.85)
remaining_payments = min(penalty_months(3), lease_term - m) * monthly_payment
termination_loss = forced_sale_value + cumulative_income - purchase_price - remaining_payments
```

**問題点:**
- `mileage` パラメータを受け取るが、スケジュール計算内で全く使用されていない
- `body_type` と `category` はここでは残価計算に使われず、減価償却は単純な定額法 (`useful_life_years * 12` の全月数ベース) であり、架装減価テーブルは適用されない。`calculate_residual_value` では適用されるので不一致がある

---

### 関数名: PricingEngine.determine_assessment
**ファイル:** `app/core/pricing.py`, line 1048
**シグネチャ:**
```python
def determine_assessment(self, effective_yield: float, breakeven: int | None, lease_term: int) -> str
```
**判定ロジック:**
```
非推奨:
  - lease_term <= 0
  - effective_yield < 0.02 (2%)
  - breakeven is None (損益分岐に到達しない)
  - breakeven / lease_term > 0.90

推奨:
  - effective_yield >= 0.05 (5%) AND breakeven / lease_term <= 0.70

要検討:
  - 上記以外
```

---

### 関数名: PricingEngine._resolve_category
**ファイル:** `app/core/pricing.py`, line 1104
**シグネチャ:**
```python
@staticmethod
def _resolve_category(input_data: dict) -> str
```
**マッピング:**
| 入力 (vehicle_class) | 出力 (category) |
|---|---|
| 小型 | SMALL |
| 中型 | MEDIUM |
| 大型 | LARGE |
| トレーラヘッド / トレーラーヘッド | TRAILER_HEAD |
| トレーラシャーシ / トレーラーシャーシ | TRAILER_CHASSIS |
| (その他/未指定) | MEDIUM (デフォルト) |

`input_data` に `category` キーが直接存在する場合はそれを `.upper()` して返す。

---

### 関数名: PricingEngine._resolve_body_type
**ファイル:** `app/core/pricing.py`, line 1123
**シグネチャ:**
```python
@staticmethod
def _resolve_body_type(body_type_raw: str) -> str
```
**マッピング:**
| 入力 | 出力 |
|---|---|
| 平ボディ | FLAT |
| バン | VAN |
| ウイング | WING |
| 冷凍・冷蔵 / 冷凍冷蔵 / 冷凍 / 冷蔵 | REFR |
| ダンプ | DUMP |
| クレーン / クレーン付 | CRAN |
| テールリフト / テールゲートリフター | TAIL_LIFT |
| ミキサー | MIXER |
| タンク / タンクローリー | TANK |
| 塵芥車 / パッカー | GARBAGE |
| (その他/未指定) | FLAT (デフォルト) |

既に英語コード (FLAT, VAN 等) の場合は `.upper()` して返す。

---

## 2. 後方互換ラッパー関数

### 関数名: _max_purchase_price
**ファイル:** `app/core/pricing.py`, line 1286
**シグネチャ:**
```python
def _max_purchase_price(book_value: int, market_median: int, body_option_value: int = 0) -> int
```
**計算式:**
```
anchor = max(book_value, market_median)
result = int(anchor * 1.10) + body_option_value
```
**問題点:** `PricingEngine.calculate_max_purchase_price` とは全く異なるロジック。Engineは `base_market_price * condition * trend * (1 - safety_margin)` だが、こちらは `max(book_value, market_median) * 1.10 + body_option_value` であり、安全マージン・トレンド・ボラティリティが一切考慮されない。

---

### 関数名: _residual_value
**ファイル:** `app/core/pricing.py`, line 1293
**シグネチャ:**
```python
def _residual_value(purchase_price: int, lease_term_months: int, residual_rate: float | None = None) -> tuple[int, float]
```
**計算式:**
```
# residual_rate が None の場合、リース期間から残価率を決定:
_DEFAULT_RESIDUAL_RATES = {12: 0.50, 24: 0.30, 36: 0.20, 48: 0.15, 60: 0.10}

# lease_term_months 以下の最小閾値に対応するレートを使用
# 例: 36ヶ月 -> 0.20
# 60ヶ月超 -> 0.05 (フォールバック)

residual = int(purchase_price * residual_rate)
return (residual, residual_rate)
```

**問題点:** `PricingEngine.calculate_residual_value` は車両カテゴリ・架装タイプ・走行距離・経過年数に基づく詳細な減価モデルを使用するが、このラッパーは単純な固定残価率テーブルのみ。全く異なる計算結果になる。

---

### 関数名: _monthly_lease_fee
**ファイル:** `app/core/pricing.py`, line 1306
**シグネチャ:**
```python
def _monthly_lease_fee(purchase_price: int, residual_value: int, lease_term_months: int, target_yield_rate: float, insurance_monthly: int = 0, maintenance_monthly: int = 0) -> int
```
**計算式:**
```
depreciable = purchase_price - residual_value
mr = target_yield_rate / 12

if mr > 0 and lease_term_months > 0:
    factor = (mr * (1 + mr)^lease_term_months) / ((1 + mr)^lease_term_months - 1)
    base = int(depreciable * factor)     # PMT計算 (年金現価係数)
else:
    base = depreciable // lease_term_months  # 単純均等割

residual_cost = int(residual_value * mr)     # 残価に対する月次利息
total = base + residual_cost + insurance_monthly + maintenance_monthly
```

**問題点:** `PricingEngine.calculate_monthly_lease_payment` はコスト積上げ方式 (元本回収 + 金利 + 管理費 + 利益マージン) であり、PMT計算ではない。二つの計算方式が共存し、`calculate_simulation_quick` はこちらのPMT方式を使用。

---

### 関数名: _assessment
**ファイル:** `app/core/pricing.py`, line 1329
**シグネチャ:**
```python
def _assessment(effective_yield: float, target_yield: float, market_deviation: float) -> str
```
**判定ロジック:**
```
推奨: effective_yield >= target_yield AND |market_deviation| <= 0.05
非推奨: effective_yield < target_yield * 0.5 OR |market_deviation| > 0.10
要検討: 上記以外
```

**問題点:** `PricingEngine.determine_assessment` とは判定基準が完全に異なる。
- Engine版: 利回り5%以上 + 損益分岐70%以内で推奨。利回り2%未満で非推奨。
- ラッパー版: 利回りが目標以上 + 市場乖離5%以内で推奨。利回りが目標の50%未満 or 市場乖離10%超で非推奨。

---

### 関数名: _build_schedule
**ファイル:** `app/core/pricing.py`, line 1339
**シグネチャ:**
```python
def _build_schedule(purchase_price: int, residual_value: int, lease_term_months: int, monthly_fee: int, target_yield_rate: float, insurance_monthly: int = 0, maintenance_monthly: int = 0) -> list
```
**計算式 (各月 m):**
```
dep_per_month = (purchase_price - residual_value) / lease_term_months
asset = max(int(purchase_price - dep_per_month * m), residual_value)
prev_asset = purchase_price - dep_per_month * (m - 1)
dep_exp = prev_asset - asset
fin_cost = int(prev_asset * (target_yield_rate / 12))
net_income = monthly_fee - insurance_monthly - maintenance_monthly
profit = net_income - dep_exp - fin_cost
term_loss = purchase_price - cumulative_income - asset
```

**問題点:**
- `PricingEngine.calculate_monthly_schedule` は `remaining_balance` (逓減残高) に金利を適用するが、`_build_schedule` は `prev_asset` (資産簿価) に金利を適用しており、金利計算の基準が異なる
- `_build_schedule` は `target_yield_rate` を金利として使用するが、Engine版は `fund_cost_rate + credit_spread + liquidity_premium` を金利として使用
- `termination_loss` の計算式も異なる

---

## 3. calculate_simulation 非同期関数

### 関数名: calculate_simulation
**ファイル:** `app/core/pricing.py`, line 1218
**シグネチャ:**
```python
async def calculate_simulation(input_data: SimulationInput, supabase: Client) -> SimulationResult
```
**処理フロー:**
1. `_fetch_market_comparables` で Supabase から類似車両の市場価格を取得
2. 取得した中央値を `{"price_yen": median, "source_site": "retail"}` として `PricingEngine.calculate` に渡す
3. 結果を `SimulationResult` Pydantic モデルに変換

**問題点:** 市場中央値を `source_site: "retail"` として渡しているため、`calculate_base_market_price` では `retail_prices` のみにデータが入り、`auction_prices` は空になる。結果として加重平均は行われず、中央値がそのまま `base_market_price` になる。

---

### 関数名: _fetch_market_comparables
**ファイル:** `app/core/pricing.py`, line 1161
**シグネチャ:**
```python
async def _fetch_market_comparables(client: Client, maker: str, model: str, body_type: str, registration_year_month: str, mileage_km: int) -> tuple[int, int]
```
**クエリ条件:**
```
- maker: 完全一致
- body_type: 完全一致
- model_year: registration_year +/- 2年
- mileage_km: +/- 50,000km
- listing_status: "active"
- price_yen: NOT NULL
```
**中央値計算:**
```
prices = sorted(...)
n = len(prices)
if n % 2 == 0:
    median = (prices[n//2 - 1] + prices[n//2]) // 2  # 整数除算
else:
    median = prices[n//2]
```

**問題点:**
- `model` (車種名) がクエリ条件に含まれておらず、同一メーカー・同一架装の全車種が比較対象になる。大型ダンプと中型ダンプが混在する可能性がある。
- 中央値計算が `// 2` (整数除算) で切り捨てされる

---

## 4. ResidualValueCalculator クラス

**ファイル:** `app/core/residual_value.py`, line 13

### 定数テーブル

**LEGAL_USEFUL_LIFE (法定耐用年数):**
| カテゴリ | 耐用年数 |
|---|---|
| 普通貨物 | 5 |
| ダンプ | 4 |
| 小型貨物 | 3 |
| 特種自動車 | 4 |
| 被けん引車 | 4 |

**_ANNUAL_MILEAGE_NORM (年間標準走行距離, km):**
| カテゴリ | km/年 |
|---|---|
| 普通貨物 | 40,000 |
| ダンプ | 30,000 |
| 小型貨物 | 25,000 |
| 特種自動車 | 20,000 |
| 被けん引車 | 50,000 |

注意: `PricingEngine.ANNUAL_STANDARD_MILEAGE` とカテゴリ名・数値が異なる (例: PricingEngine は LARGE=80,000 だが、ResidualValueCalculator は 普通貨物=40,000)

**_BODY_RETENTION (架装価値残存率係数):**
| 架装タイプ | 係数 |
|---|---|
| 平ボディ | 0.85 |
| バン | 0.90 |
| 冷凍冷蔵 | 0.75 |
| ウイング | 0.80 |
| ダンプ | 0.88 |
| タンク | 0.70 |
| クレーン | 0.65 |
| 塵芥車 | 0.60 |

---

### 関数名: calculate_used_vehicle_useful_life
**ファイル:** `app/core/residual_value.py`, line 50
**シグネチャ:**
```python
def calculate_used_vehicle_useful_life(self, legal_life: int, elapsed_years: int) -> int
```
**計算式 (中古車耐用年数簡便法):**
```
remaining = legal_life - elapsed_years
if remaining > 0:
    return max(remaining, 2)
else:
    return max(int(elapsed_years * 0.2), 2)   # 法定年数超過: 経過年数の20%
```

---

### 関数名: straight_line
**ファイル:** `app/core/residual_value.py`, line 81
**シグネチャ:**
```python
def straight_line(self, purchase_price: float, salvage_value: float, useful_life: int, elapsed_years: int) -> float
```
**計算式:**
```
annual_depreciation = (purchase_price - salvage_value) / useful_life
value = purchase_price - annual_depreciation * elapsed_years
return max(value, salvage_value)
```

---

### 関数名: declining_balance_200
**ファイル:** `app/core/residual_value.py`, line 117
**シグネチャ:**
```python
def declining_balance_200(self, purchase_price: float, useful_life: int, elapsed_years: int) -> float
```
**計算式 (200%定率法):**
```
rate = 2.0 / useful_life
sl_switch_rate = 1.0 / useful_life
guarantee_amount = purchase_price * (sl_switch_rate * 0.9)

各年:
    depreciation = value * rate
    if depreciation < guarantee_amount:
        # 定額法に切替 (改定償却率)
        sl_depreciation = value / remaining_years
        value -= sl_depreciation
    else:
        value -= depreciation

return max(value, 1.0)   # 備忘価額 1円
```

**特記:** `guarantee_amount` の計算が `purchase_price * (1/useful_life * 0.9)` であり、正確な保証率テーブル (国税庁) とは異なる簡易計算。

---

### 関数名: hybrid_prediction
**ファイル:** `app/core/residual_value.py`, line 184
**シグネチャ:**
```python
def hybrid_prediction(self, theoretical_value: float, market_data: dict[str, Any], params: Optional[dict[str, float]] = None) -> float
```
**計算式:**
```
デフォルト: market_weight_base=0.6, min_samples=3, volatility_penalty=0.5

if sample_count < min_samples:
    market_weight = market_weight_base * (sample_count / min_samples)
else:
    market_weight = market_weight_base

market_weight *= max(0, 1 - volatility * volatility_penalty)
market_weight = clamp(market_weight, 0, 1)

theory_weight = 1 - market_weight
blended = theory_weight * theoretical_value + market_weight * median_price

return max(blended, 1.0)
```

---

### 関数名: _mileage_adjustment_factor
**ファイル:** `app/core/residual_value.py`, line 243
**シグネチャ:**
```python
def _mileage_adjustment_factor(self, mileage_km: int, elapsed_months: int, category: str) -> float
```
**計算式 (段階テーブル方式):**
```
expected_km = _ANNUAL_MILEAGE_NORM[category] * (elapsed_months / 12)
ratio = mileage_km / expected_km

ratio <= 0.5  -> 1.10
ratio <= 0.8  -> 1.05
ratio <= 1.0  -> 1.00
ratio <= 1.3  -> 0.93
ratio <= 1.5  -> 0.85
ratio <= 2.0  -> 0.75
ratio >  2.0  -> 0.60
```

**問題点:** `PricingEngine.calculate_mileage_adjustment` は連続的な線形調整 (`1.0 - deviation * rate`) だが、こちらは離散的な段階テーブル。同じシステム内で走行距離調整の方式が二つ存在する。

---

### 関数名: ResidualValueCalculator.predict
**ファイル:** `app/core/residual_value.py`, line 282
**シグネチャ:**
```python
def predict(self, purchase_price: float, category: str, body_type: str, elapsed_months: int, mileage: int, market_data: Optional[dict[str, Any]] = None) -> dict[str, Any]
```
**計算式:**
```
legal_life = LEGAL_USEFUL_LIFE[category]
elapsed_years = elapsed_months // 12
useful_life = calculate_used_vehicle_useful_life(legal_life, elapsed_years)
salvage_value = max(purchase_price * 0.10, 1.0)

# シャーシ: 定額法と200%定率法の平均
sl_value = straight_line(purchase_price, salvage_value, legal_life, elapsed_years)
db_value = declining_balance_200(purchase_price, legal_life, elapsed_years)
chassis_value = (sl_value + db_value) / 2.0

# 架装価値 (購入価格の30%を架装とみなす)
body_ratio = 0.30
chassis_ratio = 0.70
body_retention = _BODY_RETENTION.get(body_type, 0.80)
body_value = purchase_price * 0.30 * body_retention^(elapsed_years / max(legal_life, 1))
chassis_component = chassis_value * 0.70 / (0.70 + 0.30)  # = chassis_value * 0.70

theoretical_value = chassis_component + body_value

# 走行距離調整
theoretical_value *= _mileage_adjustment_factor(mileage, elapsed_months, category)

# 市場データとのブレンド (hybrid_prediction)
if market_data available:
    predicted = hybrid_prediction(theoretical_value, market_data)
else:
    predicted = theoretical_value

# 万円単位に四捨五入
residual_value = int(round(predicted / 10000) * 10000)
```

**問題点:**
- `chassis_component = chassis_value * 0.70 / 1.00 = chassis_value * 0.70` であり、シャーシ自体の減価を30%割り引いている。全体として `chassis_value * 0.70 + body_value` となり、元の `chassis_value` よりも常に小さくなる設計。
- `useful_life` を計算するが `legal_life` を定額法/定率法に渡しており、`useful_life` が使われていない (中古車簡便法の結果が減価償却に反映されない)。
- `PricingEngine` からは呼ばれておらず、独立したモジュールとして存在。

---

## 5. MarketAnalyzer クラス

**ファイル:** `app/core/market_analysis.py`, line 17

### 関数名: calculate_statistics
**ファイル:** `app/core/market_analysis.py`, line 24
**シグネチャ:**
```python
def calculate_statistics(self, prices: list[float]) -> dict[str, Any]
```
**計算式:** NaN/inf 除外後、numpy で count, mean, median, min, max, std (ddof=1), q25, q75, iqr を計算。

---

### 関数名: detect_outliers
**ファイル:** `app/core/market_analysis.py`, line 77
**シグネチャ:**
```python
def detect_outliers(self, prices: list[float], method: str = "iqr", factor: float = 3.0) -> list[int]
```
**計算式:**
```
q25, q75 = percentile(prices, 25), percentile(prices, 75)
iqr = q75 - q25
lower_fence = q25 - factor * iqr    # デフォルト factor=3.0
upper_fence = q75 + factor * iqr
# fence 外のインデックスを返却
```
**特記:** factor=3.0 は非常に保守的 (通常の Tukey fence は 1.5)。4件未満のデータでは空リストを返す。

---

### 関数名: calculate_trend
**ファイル:** `app/core/market_analysis.py`, line 125
**シグネチャ:**
```python
def calculate_trend(self, price_history: list[dict[str, Any]], recent_days: int = 30, baseline_days: int = 180) -> dict[str, Any]
```
**計算式:**
```
recent_avg = mean(直近 recent_days 以内の価格)
baseline_avg = mean(直近 baseline_days 以内の価格)
trend_factor = recent_avg / baseline_avg

direction:
  trend_factor > 1.03 -> "up"
  trend_factor < 0.97 -> "down"
  else -> "stable"
```
**特記:** `baseline` は直近 180 日の全データであり、`recent` (30日) のデータも含まれる。つまり baseline は「除く recent」ではなく「recent を含む」。

---

### 関数名: calculate_volatility
**ファイル:** `app/core/market_analysis.py`, line 221
**シグネチャ:**
```python
def calculate_volatility(self, prices: list[float]) -> float
```
**計算式:**
```
CV = std(prices, ddof=1) / mean(prices)
return round(|CV|, 4)
```

---

### 関数名: find_comparable_vehicles
**ファイル:** `app/core/market_analysis.py`, line 274
**シグネチャ:**
```python
def find_comparable_vehicles(self, target: dict[str, Any], vehicles: list[dict[str, Any]], max_results: int = 10) -> list[dict[str, Any]]
```
**スコアリング (合計最大100点):**
```
メーカー完全一致: +20点 (不一致なら除外)
モデル名類似度 (Jaccard bigram): +30点 * similarity (0.3未満なら除外)
年式差 (±2年以内): +20点 * (1 - year_diff/3)  (2年超なら除外)
走行距離 (±30%以内): +20点 * (1 - mileage_ratio/0.30)  (30%超なら除外)
架装タイプ完全一致: +10点
```

---

### 関数名: calculate_deviation_rate
**ファイル:** `app/core/market_analysis.py`, line 376
**シグネチャ:**
```python
def calculate_deviation_rate(self, auction_price: float, retail_price: float) -> float
```
**計算式:**
```
deviation = (retail_price - auction_price) / retail_price
```

---

### 関数名: generate_price_distribution
**ファイル:** `app/core/market_analysis.py`, line 402
**シグネチャ:**
```python
def generate_price_distribution(self, prices: list[float], bins: int = 10) -> dict[str, Any]
```
**処理:** numpy.histogram で等間隔ビンを生成。10,000以上は万円表示。

---

## 6. calculate_simulation_quick API

**ファイル:** `app/api/simulation.py`, line 628
**エンドポイント:** `POST /api/v1/simulations/calculate`
**認証:** 不要

この関数は **後方互換ラッパー関数** (`_max_purchase_price`, `_residual_value`, `_monthly_lease_fee`, `_assessment`) を使用しており、`PricingEngine` クラスは使用していない。

### 入力パラメータ (フォームデータ):
| フィールド | 型 | デフォルト |
|---|---|---|
| maker | str | "" |
| model | str | "" |
| mileage_km | int | 0 |
| acquisition_price | int | 0 |
| book_value | int | 0 |
| body_type | str | "" |
| body_option_value | int | 0 |
| target_yield_rate | float | 8.0 (%) |
| lease_term_months | int | 36 |
| equipment | list | [] |

### 計算フロー:
```python
# 1. 最大購入価格
max_price = _max_purchase_price(book_value, acquisition_price, body_option_value)
# = int(max(book_value, acquisition_price) * 1.10) + body_option_value

# 2. 推奨購入価格
recommended_price = int(max_price * 0.95)   # 最大から5%ディスカウント

# 3. 残価
residual, residual_rate = _residual_value(recommended_price, lease_term_months)
# 36ヶ月の場合: residual_rate = 0.20, residual = int(recommended_price * 0.20)

# 4. 月額リース料
monthly_fee = _monthly_lease_fee(
    recommended_price, residual, lease_term_months,
    target_yield_rate / 100,  # 8.0 -> 0.08
    15000,                     # ハードコード保険料
    10000                      # ハードコード整備費
)

# 5. 総額
total_fee = monthly_fee * lease_term_months

# 6. 実効利回り (年率換算)
effective_yield = ((total_fee + residual - recommended_price) / recommended_price) * (12 / lease_term_months)

# 7. 判定
assessment = _assessment(effective_yield, target_yield_rate / 100, 0.05)
# 注意: market_deviation は 0.05 にハードコードされている

# 8. 損益分岐点
net_monthly = monthly_fee - 15000 - 10000   # 保険・整備費控除後
breakeven = ceil(recommended_price / net_monthly)
```

### 月次スケジュール計算 (インライン):
```python
dep_per_month = (recommended_price - residual) / lease_term_months
mr = (target_yield_rate / 100) / 12

for month in range(1, lease_term_months + 1):
    asset_value = max(int(recommended_price - dep_per_month * month), residual)
    prev_asset = recommended_price - dep_per_month * (month - 1)
    dep_expense = int(prev_asset - asset_value)
    fin_cost = int(prev_asset * mr)
    net_income = monthly_fee - 15000 - 10000
    profit = net_income - dep_expense - fin_cost
    net_fund_value = asset_value + cumulative_income
    nav_ratio = net_fund_value / recommended_price
```

**ハードコードされた値:**
- 保険料月額: 15,000円
- 整備費月額: 10,000円
- `_assessment` の `market_deviation` 引数: 0.05 (固定)

**問題点:**
- 保険料・整備費が 15,000円・10,000円にハードコードされており、`SimulationInput` の `insurance_monthly`, `maintenance_monthly` フィールドが無視される
- `_assessment` に渡す `market_deviation` が `0.05` に固定されており、実際の市場乖離が判定に反映されない (`|0.05| <= 0.05` は常に true のため、利回りが目標以上であれば常に「推奨」になる)
- Supabase 市場データへのアクセスを行わず、`acquisition_price` を `market_median` として使用

---

## 7. 二系統の計算ロジックの乖離分析

本システムには二つの独立した計算パスが存在する:

| 項目 | PricingEngine (`calculate`) | ラッパー関数 (`calculate_simulation_quick`) |
|---|---|---|
| **使用エンドポイント** | `POST /api/v1/simulations` (保存あり、認証必須) | `POST /api/v1/simulations/calculate` (保存なし、認証不要) |
| **最大購入価格** | market * condition * trend * (1-safety) | max(book, market) * 1.10 + body_option |
| **残価計算** | 定額法 + 架装減価テーブル + 走行距離調整 | 固定残価率テーブル (12M=50%, 36M=20%, etc.) |
| **月額リース料** | コスト積上げ (元本回収 + 金利 + 管理費 + 利益) | PMT計算 (年金現価係数) + 残価利息 |
| **判定基準** | 利回り5%以上 + 損益分岐70%以内 | 利回り >= 目標 + 市場乖離5%以内 |
| **市場データ** | Supabase クエリ | なし (acquisition_price をプロキシ) |
| **保険・整備費** | SimulationInput から取得 | ハードコード (15,000 + 10,000) |

### 重大な問題点:

1. **同一システム内に矛盾する二系統の計算ロジック**が存在し、ユーザーが認証済みか否かで全く異なる結果が返される

2. **`calculate_simulation_quick` の判定が事実上機能していない**: `market_deviation` が `0.05` に固定されているため、利回りが目標以上であれば常に「推奨」と判定される

3. **`ResidualValueCalculator` クラスはどこからも呼ばれていない**: `PricingEngine` も `calculate_simulation_quick` も独自の残価計算を持ち、最も精緻な `ResidualValueCalculator` は使われていない

4. **`MarketAnalyzer` クラスもコア計算パスから呼ばれていない**: 外れ値除去、トレンド分析、ボラティリティ計算などの機能が計算パイプラインに統合されていない

5. **`_fetch_market_comparables` で `model` (車種名) がクエリ条件にない**: 同メーカー・同架装の全車種が比較対象になり、不正確な中央値になる可能性

6. **`PricingEngine.calculate_from_target_yield`** (PMT計算) は `calculate` メソッドから呼ばれず、代わりにコスト積上げ方式の `calculate_monthly_lease_payment` が使用される

7. **走行距離調整が3種類存在**:
   - `PricingEngine.calculate_mileage_adjustment`: 連続線形調整
   - `ResidualValueCalculator._mileage_adjustment_factor`: 離散段階テーブル
   - `calculate_simulation_quick`: 走行距離調整なし

---

*以上*
