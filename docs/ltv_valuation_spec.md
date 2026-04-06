# LTV制御・バリュエーションシステム — 技術仕様書

**LTV Control & Valuation Engine Technical Specification**

| 項目 | 内容 |
|------|------|
| 文書バージョン | 1.0 |
| 作成日 | 2026-04-06 |
| 親文書 | specification.md (CVLPOS ソフトウェア開発仕様書) |
| ステータス | 初版 |

---

## 目次

1. [設計思想と全体構成](#1-設計思想と全体構成)
2. [バリュエーション・スタック計算モデル](#2-バリュエーションスタック計算モデル)
3. [オプション調整バリュエーション](#3-オプション調整バリュエーション)
4. [バリュートランスファー計算](#4-バリュートランスファー計算)
5. [Python変数名定義](#5-python変数名定義)
6. [アラート・制御ロジック](#6-アラート制御ロジック)

---

## 1. 設計思想と全体構成

### 1.1 基本原則

本システムのバリュエーションは以下の3層で構成される。ファンドの資産健全性を担保するため、**常に保守的な方向にバイアスをかける**設計思想を採用する。

```
┌─────────────────────────────────────────┐
│  Retail Value（小売価格）                │  ← 使用禁止（過大評価リスク）
├─────────────────────────────────────────┤
│  B2B Wholesale Floor（業者間卸売底値）   │  ← ベースライン
├─────────────────────────────────────────┤
│  Fund Capital Deployed                   │  ← LTV 60%ライン
│  = B2B Wholesale Floor × 0.60           │
└─────────────────────────────────────────┘
```

### 1.2 バリュエーション・パイプライン

```
B2Bオークションデータ取得
    ↓
外れ値除去・統計処理
    ↓
B2B Wholesale Floor 確定
    ↓
オプション調整プレミアム加算（該当車両のみ）
    ↓
LTV 60%ルール適用 → max_purchase_price 算出
    ↓
月次バリュートランスファー計算
    ↓
60%ライン維持検証 → アラート判定
```

---

## 2. バリュエーション・スタック計算モデル

### 2.1 B2B卸売相場（Wholesale Floor）の定義と取得方法

#### 2.1.1 定義

B2B Wholesale Floor（以下「卸売底値」）とは、**業者間オートオークション（AA）における成約価格のうち、統計的に保守的な水準を示す値**である。小売掲載価格は含めない。

#### 2.1.2 データソースの厳格な分離

| データソース | 用途 | 理由 |
|-------------|------|------|
| **B2Bオークション成約価格** | バリュエーションの唯一の基準 | 実際の業者間取引価格であり、流動性リスクを最も正確に反映する |
| 小売掲載価格 | **使用禁止** | 売り手の希望価格であり、実際の成約価格より平均20-40%高い。ファンドバリュエーションに使用すると担保価値を過大評価し、元本毀損リスクが発生する |

#### 2.1.3 小売価格を使用しない技術的根拠

小売価格（Retail Value）をファンドバリュエーションから排除する理由は以下の通り:

1. **流動性ディスカウントの未反映**: 小売価格は個別交渉の結果であり、即時換金時の価格（liquidation value）を反映しない。ファンドが担保実行する局面では、B2B市場での即時売却を前提とするため、小売価格は不適切
2. **売り手バイアス**: 小売掲載価格は値引き交渉を前提とした「提示価格」であり、成約価格との間に構造的な乖離（平均15-25%）が存在する
3. **サンプルバイアス**: 状態の良い車両ほど小売市場に出る傾向があり、中央値が上方にバイアスされる
4. **時間軸の不一致**: 小売での売却には平均30-90日を要するが、ファンドの担保評価は即時清算価値（mark-to-market）に基づくべきである

#### 2.1.4 B2B Wholesale Floorの算出式

同一条件の車両（メーカー・車種・年式帯・走行距離帯・架装種別が一致）のオークション成約価格集合を `P = {p₁, p₂, ..., pₙ}` とする。

**Step 1: 外れ値除去（IQR法）**

```
Q1 = percentile(P, 25)
Q3 = percentile(P, 75)
IQR = Q3 - Q1
P_filtered = { p ∈ P | Q1 - 1.5 × IQR ≤ p ≤ Q3 + 1.5 × IQR }
```

**Step 2: 保守的基準値の選定**

```
b2b_wholesale_floor = percentile(P_filtered, 25)
```

> **設計判断**: 中央値ではなく第1四分位（25パーセンタイル）を採用する。これにより、成約データの下位75%が卸売底値を上回ることになり、担保実行時の換金リスクを低減する。

**Step 3: サンプル数不足時のフォールバック**

```python
if len(P_filtered) >= min_sample_count:
    b2b_wholesale_floor = percentile(P_filtered, 25)
elif len(P_filtered) >= 3:
    # サンプル不足ペナルティ: 中央値にさらに保守的割引を適用
    b2b_wholesale_floor = median(P_filtered) × insufficient_sample_discount
else:
    # データ不足: 手動査定必須フラグを発行
    b2b_wholesale_floor = None  # → MANUAL_REVIEW_REQUIRED
```

| パラメータ | 変数名 | デフォルト値 | 説明 |
|-----------|--------|------------|------|
| 最小サンプル数 | `min_sample_count` | 5 | 統計的に信頼可能な最小件数 |
| サンプル不足割引率 | `insufficient_sample_discount` | 0.85 | サンプル3-4件時の追加ディスカウント |
| データ鮮度期限 | `data_freshness_days` | 90 | この日数より古いデータは除外 |

#### 2.1.5 データ鮮度フィルタ

```python
cutoff_date = current_date - timedelta(days=data_freshness_days)
P = { p | p.transaction_date >= cutoff_date }
```

90日を超えたデータは市場変動を反映していないため除外する。市場急変時（例: 排ガス規制変更）には `data_freshness_days` を30日に短縮するオーバーライドを適用可能とする。

### 2.2 LTV 60%ルール

#### 2.2.1 基本計算式

```
max_purchase_price = b2b_wholesale_floor × ltv_ratio
```

ここで:

```
ltv_ratio = 0.60  (固定、管理者のみ変更可能)
```

#### 2.2.2 LTV 60%の意味

| 項目 | 値 |
|------|-----|
| 卸売底値（B2B Wholesale Floor） | 100% |
| **ファンド出資上限** | **60%** |
| **安全マージン（バッファ）** | **40%** |

この40%のバッファは以下のリスクを吸収する:

| リスク要因 | 想定損失幅 | バッファ内の配分 |
|-----------|-----------|-----------------|
| 市場下落リスク（景気後退） | 10-15% | 15% |
| 流動性リスク（急速売却時の割引） | 5-10% | 10% |
| 車両状態リスク（隠れた瑕疵） | 3-5% | 5% |
| オペレーショナルリスク（売却コスト・手数料） | 3-5% | 5% |
| 予備マージン | 5% | 5% |
| **合計** | | **40%** |

#### 2.2.3 安全マージンの段階的適用

LTV基本レートは一律60%だが、車両カテゴリおよびリスク要因に応じて**追加の安全マージン**を段階的に適用する。

```
effective_ltv = ltv_ratio × category_adjustment × age_adjustment × volatility_adjustment
```

**カテゴリ調整係数（`category_adjustment`）:**

| カテゴリ | 係数 | 実効LTV | 理由 |
|---------|------|--------|------|
| 小型トラック（SMALL） | 1.00 | 60.0% | 流動性高、需要安定 |
| 中型トラック（MEDIUM） | 1.00 | 60.0% | 流動性高 |
| 大型トラック（LARGE） | 0.95 | 57.0% | 単価高、買い手限定 |
| トレーラーヘッド（TRAILER_HEAD） | 0.92 | 55.2% | 特殊用途、流動性低 |
| トレーラーシャシー（TRAILER_CHASSIS） | 0.93 | 55.8% | 特殊用途 |
| 特装車（SPECIAL） | 0.88 | 52.8% | 極めて特殊、買い手極少 |

**車齢調整係数（`age_adjustment`）:**

```python
if elapsed_years <= 5:
    age_adjustment = 1.00
elif elapsed_years <= 8:
    age_adjustment = 0.97
elif elapsed_years <= 12:
    age_adjustment = 0.93
else:
    age_adjustment = 0.88
```

**ボラティリティ調整係数（`volatility_adjustment`）:**

```python
cv = std(P_filtered) / mean(P_filtered)  # 変動係数

if cv <= 0.10:
    volatility_adjustment = 1.00  # 低ボラティリティ
elif cv <= 0.20:
    volatility_adjustment = 0.97  # 中ボラティリティ
elif cv <= 0.30:
    volatility_adjustment = 0.93  # 高ボラティリティ
else:
    volatility_adjustment = 0.88  # 極端なボラティリティ
```

#### 2.2.4 最終的な最大買取価格

```
max_purchase_price = b2b_wholesale_floor × effective_ltv
```

ここで:

```
effective_ltv = ltv_ratio × category_adjustment × age_adjustment × volatility_adjustment
```

**制約条件:**

```python
assert 0.45 <= effective_ltv <= 0.60, "実効LTVは45%-60%の範囲内であること"
```

---

## 3. オプション調整バリュエーション

### 3.1 設計方針

架装オプションの残存価値プレミアムは、**B2Bオークション市場で統計的に証明された高額転売実績を持つ架装のみ**に適用する。恣意的な上乗せによる担保過大評価を防止するため、以下の3条件を全て満たす架装のみが対象となる。

**プレミアム適格3条件:**

1. **統計的有意性**: 当該架装付き車両のオークション成約データが `min_option_sample_count`（デフォルト: 10）件以上存在すること
2. **価格プレミアムの実証**: 同一シャシー条件で架装なし車両と比較して、中央値ベースで有意なプレミアムが認められること（最低 `min_premium_threshold` = 5%以上）
3. **プレミアムの安定性**: 直近90日間のプレミアム率の変動係数（CV）が `max_premium_cv`（デフォルト: 0.30）以下であること

### 3.2 オプションプレミアム一般計算式

```
option_premium = option_base_value × option_retention_factor(t) × condition_modifier × premium_cap_factor
```

各変数:

| 変数 | 説明 |
|------|------|
| `option_base_value` | 架装の新品取得価格（円） |
| `option_retention_factor(t)` | 経過年数 `t` における残価率（後述の架装別テーブル参照） |
| `condition_modifier` | 架装状態補正（0.7-1.0、デフォルト1.0） |
| `premium_cap_factor` | プレミアム上限キャップ係数 |

### 3.3 適格架装オプション別の計算式

#### 3.3.1 パワーゲート（Power Gate / テールゲートリフター）

パワーゲートは荷台後部に装備される油圧式昇降装置であり、B2B市場での需要が安定的に高い。

**残存価値計算:**

```
power_gate_premium = pg_base_value × pg_retention(t) × pg_condition
```

**残価率テーブル `pg_retention(t)`:**

| 経過年数 (t) | 残価率 | 累積減価率 |
|-------------|--------|-----------|
| 0 | 1.00 | 0% |
| 1 | 0.82 | 18% |
| 2 | 0.68 | 32% |
| 3 | 0.56 | 44% |
| 4 | 0.46 | 54% |
| 5 | 0.38 | 62% |
| 6 | 0.31 | 69% |
| 7 | 0.25 | 75% |
| 8 | 0.20 | 80% |
| 10 | 0.12 | 88% |
| 12 | 0.07 | 93% |
| 15 | 0.03 | 97% |

**中間年数は指数減衰による補間:**

```
pg_retention(t) = exp(-λ_pg × t)
```

ここで `λ_pg = 0.20`（年間減衰率パラメータ）

**デフォルトパラメータ:**

| パラメータ | 変数名 | デフォルト値 | 範囲 |
|-----------|--------|------------|------|
| パワーゲート新品価格 | `pg_base_value` | 800,000円 | 300,000 - 2,000,000 |
| 減衰率 | `pg_decay_rate` | 0.20 | 0.10 - 0.35 |
| 状態補正 | `pg_condition` | 1.0 | 0.7 - 1.0 |

#### 3.3.2 冷凍冷蔵ユニット（Cold Storage / Refrigerator）

冷凍冷蔵ユニットは機械部品であるため、シャシーよりも減価が速い。一方、食品物流需要に支えられ、適切に整備された冷凍機は一定のプレミアムを維持する。

**残存価値計算:**

```
refr_premium = refr_base_value × refr_retention(t) × refr_condition × refr_brand_factor
```

**残価率テーブル `refr_retention(t)`:**

| 経過年数 (t) | 残価率 | 累積減価率 |
|-------------|--------|-----------|
| 0 | 1.00 | 0% |
| 1 | 0.75 | 25% |
| 2 | 0.58 | 42% |
| 3 | 0.44 | 56% |
| 4 | 0.34 | 66% |
| 5 | 0.25 | 75% |
| 6 | 0.19 | 81% |
| 7 | 0.14 | 86% |
| 8 | 0.10 | 90% |
| 10 | 0.05 | 95% |
| 12 | 0.02 | 98% |

**減衰モデル:**

```
refr_retention(t) = exp(-λ_refr × t)
```

ここで `λ_refr = 0.29`（冷凍機は機械減耗が大きいため減衰率が高い）

**ブランド補正係数 `refr_brand_factor`:**

| メーカー | 係数 | 理由 |
|---------|------|------|
| 東プレ（Topre） | 1.05 | 市場シェア高、部品入手性良好 |
| デンソー（DENSO） | 1.03 | 信頼性高 |
| 三菱重工 | 1.00 | 標準 |
| その他 | 0.95 | 市場流通少、部品入手性リスク |

**デフォルトパラメータ:**

| パラメータ | 変数名 | デフォルト値 | 範囲 |
|-----------|--------|------------|------|
| 冷凍機新品価格 | `refr_base_value` | 2,500,000円 | 1,000,000 - 6,000,000 |
| 減衰率 | `refr_decay_rate` | 0.29 | 0.20 - 0.40 |
| 状態補正 | `refr_condition` | 1.0 | 0.5 - 1.0 |
| ブランド補正 | `refr_brand_factor` | 1.0 | 0.90 - 1.10 |

#### 3.3.3 クレーン（Integrated Crane / ユニック）

クレーンは建設・運搬業界での需要が安定しており、適切に検査された個体は高い残存価値を示す。ただし、法定検査（クレーン検査証）の有効性が価値に直結する。

**残存価値計算:**

```
crane_premium = crane_base_value × crane_retention(t) × crane_condition × crane_certification_factor
```

**残価率テーブル `crane_retention(t)`:**

| 経過年数 (t) | 残価率 | 累積減価率 |
|-------------|--------|-----------|
| 0 | 1.00 | 0% |
| 1 | 0.85 | 15% |
| 2 | 0.72 | 28% |
| 3 | 0.62 | 38% |
| 4 | 0.53 | 47% |
| 5 | 0.45 | 55% |
| 6 | 0.38 | 62% |
| 7 | 0.32 | 68% |
| 8 | 0.27 | 73% |
| 10 | 0.18 | 82% |
| 12 | 0.12 | 88% |
| 15 | 0.06 | 94% |

**減衰モデル:**

```
crane_retention(t) = exp(-λ_crane × t)
```

ここで `λ_crane = 0.17`（クレーンは金属構造物であり減衰が比較的緩やか）

**クレーン検査証補正 `crane_certification_factor`:**

| 検査状態 | 係数 | 説明 |
|---------|------|------|
| 有効（残6ヶ月超） | 1.00 | 標準 |
| 有効（残6ヶ月以内） | 0.95 | 更新コストを反映 |
| 期限切れ | 0.80 | 再検査費用を減額 |
| 不明 | 0.75 | 最大リスクを想定 |

**デフォルトパラメータ:**

| パラメータ | 変数名 | デフォルト値 | 範囲 |
|-----------|--------|------------|------|
| クレーン新品価格 | `crane_base_value` | 3,000,000円 | 1,500,000 - 8,000,000 |
| 減衰率 | `crane_decay_rate` | 0.17 | 0.10 - 0.25 |
| 状態補正 | `crane_condition` | 1.0 | 0.6 - 1.0 |
| 検査証補正 | `crane_certification_factor` | 1.0 | 0.75 - 1.0 |

### 3.4 プレミアム加算の上限ルール（過大評価防止）

架装プレミアムの合計が車両全体の評価額に占める比率を制限し、架装過大評価による元本毀損を防止する。

#### 3.4.1 プレミアム上限キャップ

```
total_option_premium = Σ(option_premium_i)  # 全架装プレミアムの合計

# キャップ1: 個別架装の上限（車両本体価格の一定割合）
for each option_premium_i:
    option_premium_i = min(option_premium_i, b2b_wholesale_floor × max_single_option_ratio)

# キャップ2: 合計の上限
max_total_premium = b2b_wholesale_floor × max_total_option_ratio
total_option_premium_capped = min(total_option_premium, max_total_premium)
```

**上限パラメータ:**

| パラメータ | 変数名 | デフォルト値 | 説明 |
|-----------|--------|------------|------|
| 個別架装上限比率 | `max_single_option_ratio` | 0.15 | 1架装あたり車両本体の15%まで |
| 合計上限比率 | `max_total_option_ratio` | 0.25 | 全架装合計で車両本体の25%まで |

#### 3.4.2 プレミアム適用後の最大買取価格

```
adjusted_b2b_floor = b2b_wholesale_floor + total_option_premium_capped
max_purchase_price = adjusted_b2b_floor × effective_ltv
```

**重要**: LTV 60%ルールは、架装プレミアム加算後の`adjusted_b2b_floor`に対して適用される。これにより、架装プレミアムにも同一のLTV制約が課される。

#### 3.4.3 プレミアム健全性チェック

```python
def validate_option_premium(option_premium, b2b_floor, option_type):
    ratio = option_premium / b2b_floor if b2b_floor > 0 else 0
    
    if ratio > max_single_option_ratio:
        logger.warning(
            "架装プレミアム上限超過",
            option_type=option_type,
            ratio=ratio,
            capped_at=max_single_option_ratio
        )
        return b2b_floor * max_single_option_ratio
    
    return option_premium
```

---

## 4. バリュートランスファー計算

### 4.1 概念

バリュートランスファー（Value Transfer）とは、リース期間を通じて車両の物理的資産価値が減少する一方、リース料の累積回収により現金資産が積み上がる過程を定量的にモデル化したものである。

```
Net Fund Asset Value(t) = Physical Vehicle Value(t) + Accumulated Cash Recovery(t)
```

**設計目標**: `Net Fund Asset Value(t)` が36ヶ月のリース期間を通じて、常に当初ファンド出資額の60%以上を維持すること。

### 4.2 月次Net Fund Asset Value計算式

#### 4.2.1 月次計算の全体式

月 `t`（t = 0, 1, 2, ..., T、Tはリース期間月数）における各値:

```
net_fund_asset_value(t) = physical_vehicle_value(t) + accumulated_cash_recovery(t)
```

```
net_fund_asset_value_ratio(t) = net_fund_asset_value(t) / initial_capital_deployed
```

ここで `initial_capital_deployed = max_purchase_price`（ファンドの初期出資額）

#### 4.2.2 Physical Vehicle Value 減価カーブ

物理的車両価値の月次減価には、**修正指数減衰モデル**を採用する。直線減価と比較して、初期の減価が速く後半で緩やかになる実市場の減価パターンを反映する。

**修正指数減衰モデル:**

```
physical_vehicle_value(t) = b2b_wholesale_floor × [ salvage_floor + (1 - salvage_floor) × exp(-μ × t/12) ]
```

ここで:

| 変数 | 説明 | デフォルト値 |
|------|------|------------|
| `μ` | 年間減衰速度パラメータ | カテゴリ別（後述） |
| `salvage_floor` | 最低残存率（スクラップ価値相当） | 0.10 |
| `t` | 経過月数 | 0 - T |

**カテゴリ別の減衰速度 `μ`:**

| カテゴリ | μ | 36ヶ月後の残価率 | 60ヶ月後の残価率 |
|---------|---|----------------|----------------|
| SMALL | 0.25 | 52.3% | 37.5% |
| MEDIUM | 0.22 | 55.1% | 40.7% |
| LARGE | 0.20 | 57.5% | 43.6% |
| TRAILER_HEAD | 0.18 | 59.8% | 46.3% |
| TRAILER_CHASSIS | 0.15 | 63.5% | 51.0% |

**代替モデル: 直線減価（参考）**

```
physical_vehicle_value_linear(t) = b2b_wholesale_floor × max(salvage_floor, 1 - depreciation_rate_monthly × t)
```

ここで:

```
depreciation_rate_monthly = (1 - target_residual_rate) / lease_term_months
```

**ピッチデッキ整合性確認:**

| 時点 | ピッチデッキ記載 | 指数減衰モデル（LARGE, μ=0.20） | 直線モデル |
|------|-----------------|-------------------------------|-----------|
| Month 01 | Asset = 100% | 100.0% | 100.0% |
| Month 18 | (未記載) | 76.1% | 65.0% |
| Month 36 | Asset ≈ 30% | 57.5% → LTV後 ≈ 34.5% | 30.0% |

> **注記**: ピッチデッキの「Asset=30%」はファンド出資額（LTV 60%適用後の金額）に対する比率と解釈する。つまり `physical_vehicle_value(36) / initial_capital_deployed ≈ 0.30` を示す。卸売底値に対しては `0.30 × 0.60 = 0.18`（18%）に相当する。

#### 4.2.3 Accumulated Cash Recovery 積上げ

```
accumulated_cash_recovery(t) = Σ_{k=1}^{t} monthly_net_cash_inflow(k)
```

**月次ネットキャッシュインフロー:**

```
monthly_net_cash_inflow(k) = monthly_lease_fee - monthly_management_cost - monthly_financing_cost
```

各構成要素:

```
monthly_lease_fee        = (purchase_price - residual_value) / T + interest_component + management_fee + profit_margin
monthly_management_cost  = purchase_price × monthly_management_fee_rate + fixed_monthly_admin_cost
monthly_financing_cost   = outstanding_principal(k) × (fund_cost_rate / 12)
```

ここで `outstanding_principal(k)` は月 `k` 時点のファンドの未回収元本:

```
outstanding_principal(k) = initial_capital_deployed - accumulated_principal_recovery(k-1)
accumulated_principal_recovery(k) = Σ_{j=1}^{k} (monthly_lease_fee - monthly_financing_cost_at(j))
```

**ピッチデッキ整合性確認:**

| 時点 | ピッチデッキ記載 | 計算モデル |
|------|-----------------|-----------|
| Month 01 | Cash = 0% | 0.0% |
| Month 36 | Cash ≈ 80% | リース料総額 / 初期出資額 (目標: ≥ 80%) |

### 4.3 60%ライン維持の検証ロジック

#### 4.3.1 月次検証計算

リース期間の各月において、以下の検証を実施する:

```python
def verify_ltv_maintenance(t: int) -> LtvCheckResult:
    """月次LTV維持検証"""
    
    pvv = physical_vehicle_value(t)
    acr = accumulated_cash_recovery(t)
    nav = pvv + acr
    nav_ratio = nav / initial_capital_deployed
    
    # 60%ラインとの比較
    threshold = ltv_maintenance_threshold  # デフォルト: 0.60
    
    if nav_ratio >= threshold:
        status = "HEALTHY"
    elif nav_ratio >= threshold * warning_buffer:  # デフォルト: 0.90 → 実質54%
        status = "WARNING"
    elif nav_ratio >= threshold * critical_buffer:  # デフォルト: 0.80 → 実質48%
        status = "CRITICAL"
    else:
        status = "BREACH"
    
    return LtvCheckResult(
        month=t,
        physical_vehicle_value=pvv,
        accumulated_cash_recovery=acr,
        net_asset_value=nav,
        nav_ratio=nav_ratio,
        status=status,
    )
```

#### 4.3.2 アラート条件と対応アクション

| ステータス | NAV比率 | 閾値（デフォルト） | アラート | 対応アクション |
|-----------|---------|------------------|---------|---------------|
| **HEALTHY** | ≥ 60% | `ltv_maintenance_threshold` (0.60) | なし | 通常運用 |
| **WARNING** | 54% - 60% | `threshold × 0.90` | 黄色アラート | ファンドマネージャーに通知。次月再評価を実施 |
| **CRITICAL** | 48% - 54% | `threshold × 0.80` | 赤色アラート | 経営層に即時報告。追加担保または早期回収の検討 |
| **BREACH** | < 48% | `threshold × 0.80` 未満 | 緊急アラート | リース契約の条件変更交渉または担保実行プロセスを起動 |

#### 4.3.3 ストレステスト

各リース案件について、以下のストレスシナリオでの60%ライン維持を検証する:

```python
stress_scenarios = {
    "base":        {"market_shock": 0.00, "vacancy_months": 0},
    "mild":        {"market_shock": -0.10, "vacancy_months": 2},
    "moderate":    {"market_shock": -0.20, "vacancy_months": 4},
    "severe":      {"market_shock": -0.30, "vacancy_months": 6},
}
```

```python
def stress_test(scenario: dict) -> list[LtvCheckResult]:
    """ストレスシナリオにおけるLTV推移を計算"""
    results = []
    for t in range(1, lease_term_months + 1):
        pvv = physical_vehicle_value(t) * (1 + scenario["market_shock"])
        
        if t <= scenario["vacancy_months"]:
            acr_increment = 0  # リース料未収
        else:
            acr_increment = monthly_net_cash_inflow(t)
        
        acr = sum(increments[:t])
        nav = pvv + acr
        results.append(verify_ltv_maintenance_with(t, pvv, acr))
    
    return results
```

**承認基準**: "moderate" シナリオ（市場20%下落 + 4ヶ月空室）でも全月においてNAV比率が48%（CRITICAL閾値）を下回らないこと。

### 4.4 月次スケジュール出力フォーマット

```python
@dataclass
class MonthlyValueTransfer:
    month: int                          # 月番号 (1-based)
    physical_vehicle_value: int         # 車両物理的価値（円）
    physical_value_ratio: float         # 車両価値/初期出資額
    monthly_lease_income: int           # 当月リース料収入（円）
    monthly_net_cash: int               # 当月ネットキャッシュ（円）
    accumulated_cash_recovery: int      # 累積キャッシュ回収（円）
    cash_recovery_ratio: float          # キャッシュ回収/初期出資額
    net_asset_value: int                # NAV（円）
    nav_ratio: float                    # NAV/初期出資額
    ltv_status: str                     # HEALTHY/WARNING/CRITICAL/BREACH
```

---

## 5. Python変数名定義

### 5.1 バリュエーション・スタック変数

| 変数名 | 型 | デフォルト値 | 許容範囲 | 説明 |
|--------|-----|------------|---------|------|
| `b2b_wholesale_floor` | `float` | 算出値 | > 0 | B2B卸売底値（円） |
| `ltv_ratio` | `float` | 0.60 | 0.45 - 0.70 | LTV基本比率 |
| `effective_ltv` | `float` | 算出値 | 0.45 - 0.60 | 調整後LTV |
| `max_purchase_price` | `float` | 算出値 | > 0 | 最大買取価格（円） |
| `category_adjustment` | `float` | 1.00 | 0.80 - 1.00 | カテゴリ調整係数 |
| `age_adjustment` | `float` | 1.00 | 0.80 - 1.00 | 車齢調整係数 |
| `volatility_adjustment` | `float` | 1.00 | 0.80 - 1.00 | ボラティリティ調整係数 |
| `min_sample_count` | `int` | 5 | 3 - 20 | 最小サンプル件数 |
| `insufficient_sample_discount` | `float` | 0.85 | 0.70 - 0.95 | サンプル不足時ディスカウント |
| `data_freshness_days` | `int` | 90 | 30 - 180 | データ鮮度期限（日） |

### 5.2 オプション調整変数

| 変数名 | 型 | デフォルト値 | 許容範囲 | 説明 |
|--------|-----|------------|---------|------|
| `pg_base_value` | `int` | 800,000 | 300,000 - 2,000,000 | パワーゲート新品価格（円） |
| `pg_decay_rate` | `float` | 0.20 | 0.10 - 0.35 | パワーゲート年間減衰率 |
| `pg_condition` | `float` | 1.0 | 0.7 - 1.0 | パワーゲート状態補正 |
| `refr_base_value` | `int` | 2,500,000 | 1,000,000 - 6,000,000 | 冷凍機新品価格（円） |
| `refr_decay_rate` | `float` | 0.29 | 0.20 - 0.40 | 冷凍機年間減衰率 |
| `refr_condition` | `float` | 1.0 | 0.5 - 1.0 | 冷凍機状態補正 |
| `refr_brand_factor` | `float` | 1.0 | 0.90 - 1.10 | 冷凍機ブランド補正 |
| `crane_base_value` | `int` | 3,000,000 | 1,500,000 - 8,000,000 | クレーン新品価格（円） |
| `crane_decay_rate` | `float` | 0.17 | 0.10 - 0.25 | クレーン年間減衰率 |
| `crane_condition` | `float` | 1.0 | 0.6 - 1.0 | クレーン状態補正 |
| `crane_certification_factor` | `float` | 1.0 | 0.75 - 1.0 | クレーン検査証補正 |
| `max_single_option_ratio` | `float` | 0.15 | 0.05 - 0.25 | 個別架装上限比率 |
| `max_total_option_ratio` | `float` | 0.25 | 0.10 - 0.40 | 全架装合計上限比率 |
| `min_option_sample_count` | `int` | 10 | 5 - 30 | プレミアム適格最小サンプル数 |
| `min_premium_threshold` | `float` | 0.05 | 0.03 - 0.15 | プレミアム適格最小閾値 |
| `max_premium_cv` | `float` | 0.30 | 0.15 - 0.50 | プレミアム安定性CV上限 |

### 5.3 バリュートランスファー変数

| 変数名 | 型 | デフォルト値 | 許容範囲 | 説明 |
|--------|-----|------------|---------|------|
| `initial_capital_deployed` | `float` | 算出値 | > 0 | 初期ファンド出資額（円） |
| `physical_vehicle_value` | `float` | 算出値 | ≥ 0 | 月次の車両物理的価値（円） |
| `accumulated_cash_recovery` | `float` | 算出値 | ≥ 0 | 累積キャッシュ回収額（円） |
| `net_fund_asset_value` | `float` | 算出値 | ≥ 0 | ファンド純資産価値（円） |
| `nav_ratio` | `float` | 算出値 | 0.0 - 2.0 | NAV/初期出資額 |
| `salvage_floor` | `float` | 0.10 | 0.05 - 0.20 | 最低残存率 |
| `depreciation_mu` | `float` | カテゴリ別 | 0.10 - 0.35 | 年間減衰速度パラメータ |
| `ltv_maintenance_threshold` | `float` | 0.60 | 0.50 - 0.70 | LTV維持閾値 |
| `warning_buffer` | `float` | 0.90 | 0.85 - 0.95 | WARNING判定バッファ |
| `critical_buffer` | `float` | 0.80 | 0.70 - 0.90 | CRITICAL判定バッファ |
| `monthly_management_fee_rate` | `float` | 0.002 | 0.001 - 0.005 | 月次管理費率 |
| `fixed_monthly_admin_cost` | `int` | 5,000 | 0 - 20,000 | 固定月次管理費（円） |
| `fund_cost_rate` | `float` | 0.020 | 0.005 - 0.050 | ファンドコスト率（年率） |
| `lease_term_months` | `int` | 36 | 12 - 84 | リース期間（月） |

### 5.4 ストレステスト変数

| 変数名 | 型 | デフォルト値 | 許容範囲 | 説明 |
|--------|-----|------------|---------|------|
| `stress_market_shock_mild` | `float` | -0.10 | -0.20 - 0.00 | 軽度シナリオの市場下落率 |
| `stress_market_shock_moderate` | `float` | -0.20 | -0.35 - -0.10 | 中度シナリオの市場下落率 |
| `stress_market_shock_severe` | `float` | -0.30 | -0.50 - -0.20 | 重度シナリオの市場下落率 |
| `stress_vacancy_mild` | `int` | 2 | 0 - 6 | 軽度シナリオの空室月数 |
| `stress_vacancy_moderate` | `int` | 4 | 2 - 9 | 中度シナリオの空室月数 |
| `stress_vacancy_severe` | `int` | 6 | 3 - 12 | 重度シナリオの空室月数 |

---

## 6. アラート・制御ロジック

### 6.1 リアルタイム検証トリガー

以下のイベントが発生した際に、当該車両のLTV検証を再実行する:

| トリガーイベント | 再検証範囲 | 即時実行 |
|----------------|-----------|---------|
| 新規オークションデータ取得 | 該当車種カテゴリ全件 | No（日次バッチ） |
| パラメータ変更（管理者） | 全件 | No（変更確定後バッチ） |
| 月次締め処理 | 全件 | Yes |
| 手動トリガー | 指定案件 | Yes |

### 6.2 ダッシュボード表示項目

| 項目 | 計算式 | 閾値 |
|------|--------|------|
| ポートフォリオ加重平均NAV比率 | `Σ(nav_ratio_i × weight_i)` | ≥ 65% |
| BREACH案件数 | `count(status == "BREACH")` | = 0 |
| CRITICAL案件数 | `count(status == "CRITICAL")` | ≤ 2 |
| WARNING案件数 | `count(status == "WARNING")` | 表示のみ |
| 最低NAV比率案件 | `min(nav_ratio_i)` | ≥ 48% |

### 6.3 既存コードとの整合性

本仕様は既存の `app/core/pricing.py` の `PricingEngine` および `app/core/residual_value.py` の `ResidualValueCalculator` を拡張する形で実装する。

| 既存モジュール | 拡張内容 |
|---------------|---------|
| `PricingEngine.calculate_base_market_price()` | B2B専用モードの追加（`use_b2b_only=True`フラグ） |
| `PricingEngine.calculate_max_purchase_price()` | LTV 60%ルールの適用オプション追加 |
| `PricingEngine.calculate_safety_margin()` | 段階的安全マージン（カテゴリ×車齢×ボラティリティ）の統合 |
| `PricingEngine.calculate_monthly_schedule()` | バリュートランスファー列の追加 |
| `ResidualValueCalculator` | オプション調整プレミアム計算メソッドの追加 |
| `SimulationResult` | `nav_ratio`, `ltv_status`, `stress_test_results` フィールドの追加 |
| `MonthlyScheduleItem` | `physical_vehicle_value`, `accumulated_cash_recovery`, `nav_ratio`, `ltv_status` フィールドの追加 |

---

*以上*
