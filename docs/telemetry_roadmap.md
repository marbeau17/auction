# テレメトリー連携仕様 --- 将来フェーズ（Phase 3+）ロードマップ

**Commercial Vehicle Leaseback Pricing Optimization System（CVLPOS）拡張仕様**

| 項目 | 内容 |
|------|------|
| 文書バージョン | 0.1（ドラフト） |
| 作成日 | 2026-04-06 |
| ステータス | 将来構想 |
| 前提文書 | [ソフトウェア開発仕様書 v1.0](./specification.md) |
| ビジョン | "Beyond Financing --- Toward Dynamic Infrastructure Upgrades" |

---

## 目次

1. [概要とビジョン](#1-概要とビジョン)
2. [フェーズ定義](#2-フェーズ定義)
3. [車両テレメトリーデータ統合](#3-車両テレメトリーデータ統合)
4. [ダイナミックプライシングエンジン](#4-ダイナミックプライシングエンジン)
5. [ESGトランジション支援](#5-esgトランジション支援)
6. [予知保全連携](#6-予知保全連携)
7. [投資家向けレポーティング](#7-投資家向けレポーティング)
8. [データベース設計（追加テーブル）](#8-データベース設計追加テーブル)
9. [APIエンドポイント](#9-apiエンドポイント)
10. [セキュリティ要件](#10-セキュリティ要件)
11. [非機能要件](#11-非機能要件)

---

## 1. 概要とビジョン

### 1.1 ピッチデッキ Page 10 からの位置づけ

本仕様書は、ピッチデッキ最終ページ「Beyond Financing --- Toward Dynamic Infrastructure Upgrades」に示された将来ビジョンを、CVLPOSの技術仕様として具体化するものである。

```
┌─────────────────────────────────────────────────────────────────┐
│                   Live Vehicle Telemetry                        │
│     OBD-II / テレマティクスデバイス → リアルタイムデータ収集        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               Dynamic Pricing Engine（中核）                    │
│  テレメトリーデータ + 市場相場 + 減価償却モデル → 連続的資産評価    │
└──────────┬──────────────────────────────────────┬───────────────┘
           │                                      │
           ▼                                      ▼
┌────────────────────────────┐   ┌────────────────────────────────┐
│  Logistics ESG Transitions │   │         Investors              │
│  ディーゼル→高効率車両への   │   │  高い回復力を持つ               │
│  ブリッジキャピタル提供      │   │  オルタナティブ資産クラス        │
│  フリート転換支援            │   │  下方リスク保護と安定利回り      │
└────────────────────────────┘   └────────────────────────────────┘
                         │
                         ▼
          「A Fortified Engine of Capital Generation」
           強靭な資本創出エンジンの実現
```

### 1.2 現行システムとの関係

現行CVLPOSは、スクレイピングによるオークション相場データに基づく**静的な**（スナップショット時点の）資産評価を行う。Phase 3+では、これをリアルタイムテレメトリーデータに基づく**動的な**（連続的な）資産評価へと進化させる。

| 観点 | Phase 0-2（現行） | Phase 3+（本仕様） |
|------|------------------|-------------------|
| データソース | オークション相場（定期バッチ取得） | オークション相場 + 車両テレメトリー（リアルタイム） |
| 評価方式 | スナップショット時点の静的評価 | 連続的なライブ評価 |
| 残価予測 | 統計モデル（年式・走行距離ベース） | テレメトリー補正付き動的予測 |
| リスク検知 | 定期レビュー | 自動異常検知・即時アラート |
| ESG連携 | なし | CO2排出量計算・グリーンボンド連携 |
| 投資家向け | なし | リアルタイムポートフォリオレポート |

---

## 2. フェーズ定義

Phase 3を3つのサブフェーズに分割し、段階的にテレメトリー連携を実現する。

| サブフェーズ | 名称 | 想定期間 | 目的 |
|-------------|------|---------|------|
| Phase 3a | テレメトリー基盤構築 | 6週間 | データ受信基盤、vehicle_telemetryテーブル、基本API |
| Phase 3b | ダイナミックプライシング | 6週間 | リアルタイム資産価値更新、異常検知、予知保全 |
| Phase 3c | ESG・投資家連携 | 4週間 | ESGメトリクス、グリーンボンド連携、投資家ダッシュボード |

### 2.1 前提条件

- Phase 2（本番リリース）が完了していること
- リースバック対象車両にOBD-IIまたはテレマティクスデバイスが装着されていること
- テレメトリーデバイスベンダーとのAPI連携契約が締結されていること

---

## 3. 車両テレメトリーデータ統合

### 3.1 対応デバイス・プロトコル

| 項目 | 仕様 |
|------|------|
| 物理インターフェース | OBD-II（J1962コネクタ）、CAN-Bus |
| 商用車規格 | J1939（大型商用車標準） |
| 通信プロトコル（受信） | MQTT v5.0（推奨）、Webhook（HTTPS POST） |
| デバイスベンダー想定 | SmartDrive、Samsara、デンソーテン等 |

### 3.2 取得データ項目

| データ項目 | PID/SPN | データ型 | 単位 | 取得頻度 | 説明 |
|-----------|---------|---------|------|---------|------|
| 走行距離（累積） | SPN 245 | integer | km | 1回/分（走行中） | オドメーターの累積値 |
| エンジン稼働時間 | SPN 247 | integer | 時間 | 1回/5分 | エンジン総稼働時間 |
| 瞬間燃料消費率 | SPN 183 | float | L/h | 1回/分（走行中） | 瞬時燃料消費量 |
| 累積燃料消費 | SPN 250 | float | L | 1回/5分 | 累積消費燃料量 |
| エンジン冷却水温 | SPN 110 | float | ℃ | 1回/分 | 正常範囲: 80-105℃ |
| エンジン油温 | SPN 175 | float | ℃ | 1回/5分 | 正常範囲: 90-120℃ |
| エンジン回転数 | SPN 190 | integer | rpm | 1回/秒（走行中） | 瞬時RPM |
| DTC（故障コード） | - | string[] | - | イベント駆動 | アクティブ故障コードのリスト |
| GPS位置情報 | - | float[2] | 度 | 1回/分 | [緯度, 経度] |
| GPS速度 | - | float | km/h | 1回/分 | GPS由来の車速 |
| バッテリー電圧 | SPN 168 | float | V | 1回/5分 | 車両バッテリー電圧 |
| DPFすす蓄積率 | SPN 3251 | float | % | 1回/30分 | DPFの詰まり度合い |

### 3.3 データ受信アーキテクチャ

```
テレマティクスデバイス
    │
    ├─── MQTT ───→ [AWS IoT Core / EMQX] ───→ [Ingest Worker]
    │                                              │
    └─── Webhook ─→ [API Gateway] ──────────→ [Ingest Worker]
                                                   │
                                                   ▼
                                        ┌──────────────────┐
                                        │  メッセージキュー  │
                                        │  (Redis Streams)  │
                                        └────────┬─────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              ▼                  ▼                  ▼
                    [テレメトリー     [異常検知         [集約・
                     永続化]          エンジン]          ダウンサンプリング]
                        │                │                    │
                        ▼                ▼                    ▼
                   vehicle_          telemetry_          TimescaleDB
                   telemetry         alerts              (時系列集約)
```

### 3.4 MQTT トピック設計

```
cvlpos/telemetry/{device_id}/data        # 定期データ送信
cvlpos/telemetry/{device_id}/dtc         # 故障コード（イベント駆動）
cvlpos/telemetry/{device_id}/status      # デバイス生死監視
cvlpos/telemetry/{device_id}/command     # デバイスへのコマンド送信
```

### 3.5 Webhookペイロード仕様

```json
{
  "device_id": "DEV-20260101-0001",
  "vehicle_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-04-06T10:30:00+09:00",
  "data": {
    "odometer_km": 245320,
    "engine_hours": 8420,
    "fuel_consumption_total_l": 98210.5,
    "fuel_rate_lph": 12.3,
    "coolant_temp_c": 92.1,
    "oil_temp_c": 105.3,
    "rpm": 1850,
    "battery_voltage": 26.4,
    "dpf_soot_pct": 35.2,
    "gps": {
      "lat": 35.6812,
      "lng": 139.7671,
      "speed_kmh": 65.2
    },
    "dtc_codes": []
  },
  "metadata": {
    "firmware_version": "2.1.0",
    "signal_strength_dbm": -72
  }
}
```

### 3.6 データ保持ポリシー

| データ区分 | 解像度 | 保持期間 | ストレージ |
|-----------|--------|---------|-----------|
| 生データ（全項目） | 受信そのまま | 30日 | Supabase (PostgreSQL) |
| 1時間集約 | 平均・最大・最小 | 1年 | Supabase (PostgreSQL) |
| 1日集約 | 平均・最大・最小・走行距離差分 | 5年（リース期間+1年） | Supabase (PostgreSQL) |
| 異常イベント | イベント単位 | 無期限 | Supabase (PostgreSQL) |

---

## 4. ダイナミックプライシングエンジン

### 4.1 リアルタイム資産価値更新

現行の静的評価式:

```
max_purchase_price = base_market_price × condition_factor × trend_factor × (1 - safety_margin_rate)
```

テレメトリー拡張後の動的評価式:

```
dynamic_asset_value = base_market_price
                      × condition_factor
                      × trend_factor
                      × telemetry_health_score
                      × mileage_pace_factor
                      × (1 - safety_margin_rate)
```

### 4.2 新規パラメータ定義

#### 4.2.1 テレメトリーヘルススコア (`telemetry_health_score`)

車両の現在の状態を0.0〜1.0で定量化する複合指標。

```
telemetry_health_score = Σ(component_score_i × component_weight_i)
```

| コンポーネント | 重み | スコア算出ロジック |
|--------------|------|-----------------|
| エンジン状態 | 0.30 | DTC未発生=1.0、注意DTC=0.7、重大DTC=0.3 |
| 冷却水温正常性 | 0.10 | 80-105℃=1.0、逸脱度に応じて減点 |
| オイル温度正常性 | 0.10 | 90-120℃=1.0、逸脱度に応じて減点 |
| DPF状態 | 0.15 | すす蓄積率: 0-50%=1.0、50-80%=0.7、80%超=0.3 |
| バッテリー電圧 | 0.10 | 24V系: 25.5-28.5V=1.0、範囲外は減点 |
| アイドリング比率 | 0.10 | 全稼働時間中のアイドリング比率（低い方が良好） |
| 急加減速頻度 | 0.15 | 過去30日の急加減速回数/走行km（低い方が良好） |

#### 4.2.2 走行距離ペース係数 (`mileage_pace_factor`)

リース期間中の走行距離の進捗ペースを評価し、残価予測を動的に補正する。

```
expected_daily_km = contractual_annual_km / 365
actual_daily_km = (current_odometer - start_odometer) / elapsed_days
pace_ratio = actual_daily_km / expected_daily_km

if pace_ratio <= 1.0:
    mileage_pace_factor = 1.0 + (1.0 - pace_ratio) × upside_bonus_rate   # 最大1.05
elif pace_ratio <= 1.3:
    mileage_pace_factor = 1.0 - (pace_ratio - 1.0) × mild_penalty_rate   # 線形減少
else:
    mileage_pace_factor = 1.0 - (pace_ratio - 1.0) × severe_penalty_rate # 急激な減少
```

| パラメータ | デフォルト値 | 説明 |
|-----------|-------------|------|
| `contractual_annual_km` | 60,000 | 契約上の年間想定走行距離 |
| `upside_bonus_rate` | 0.05 | 低走行時の上方補正上限 |
| `mild_penalty_rate` | 0.15 | 1.0-1.3倍ペースの減価係数 |
| `severe_penalty_rate` | 0.30 | 1.3倍超ペースの減価係数 |

### 4.3 異常検知とLTV再計算トリガー

以下の条件を検知した場合、即座にLTV（Loan-to-Value）の再計算をトリガーする。

| トリガー条件 | 検知ロジック | 緊急度 | アクション |
|-------------|------------|--------|----------|
| 急激な走行距離増加 | 日次走行距離が過去30日平均の2倍超を3日連続 | 中 | LTV再計算、営業担当通知 |
| エンジン重大DTC | P0xxx系のクリティカルDTCを検知 | 高 | LTV再計算、即時アラート、メンテナンス推奨 |
| 冷却水温異常 | 115℃超を30分以上持続 | 高 | 即時アラート、走行停止推奨 |
| バッテリー電圧低下 | 23V以下を検知 | 中 | メンテナンス推奨通知 |
| DPF過蓄積 | すす蓄積率90%超 | 中 | DPF再生指示、メンテナンス予約推奨 |
| 長期未稼働 | エンジン稼働が14日以上ゼロ | 低 | 状況確認通知（事業停止リスク評価） |
| GPS位置異常 | 管轄外エリアへの長期移動 | 低 | 状況確認通知 |

### 4.4 LTV再計算フロー

```
[異常検知エンジン]
      │
      ▼
[telemetry_alerts INSERT]
      │
      ▼
[LTV再計算ワーカー起動]
      │
      ├── 最新テレメトリーデータ取得
      ├── telemetry_health_score 再計算
      ├── mileage_pace_factor 再計算
      ├── dynamic_asset_value 再計算
      │
      ▼
[simulations.result_summary_json 更新]
      │
      ├── LTV閾値超過？ ──YES──→ [ファンドマネージャー即時通知]
      │                           [ウォッチリスト登録]
      └── NO ──→ [定期レポートに反映]
```

---

## 5. ESGトランジション支援

### 5.1 ディーゼル→高効率車両への切替支援スキーム

ピッチデッキの「Logistics ESG Transitions」ビジョンに基づき、フリートの脱炭素化を金融面から支援するスキームを実装する。

#### 5.1.1 トランジション対象判定

```
transition_score = fuel_inefficiency_score × 0.4
                 + vehicle_age_score × 0.3
                 + maintenance_cost_score × 0.2
                 + emission_standard_score × 0.1
```

| 指標 | スコア算出方法 |
|------|--------------|
| `fuel_inefficiency_score` | テレメトリー燃費データ vs 同型車平均。悪いほど高スコア |
| `vehicle_age_score` | 経過年数/耐用年数。古いほど高スコア |
| `maintenance_cost_score` | 過去12ヶ月のDTC発生頻度。多いほど高スコア |
| `emission_standard_score` | 排ガス規制適合度。旧規制ほど高スコア |

`transition_score >= 0.7` の車両を「トランジション推奨車両」としてフラグ立てする。

#### 5.1.2 切替支援フロー

```
[トランジション推奨車両の特定]
      │
      ▼
[運送会社への提案生成]
  ├── 現行車両の残存リース料清算シミュレーション
  ├── 新規高効率車両のリースバック条件提示
  └── トータルコスト比較（TCO分析）
      │
      ▼
[ブリッジファイナンス提供]
  ├── 旧車両の残存価値を新車両の頭金に充当
  └── ESGプレミアム金利（通常比-0.5%〜-1.0%）の適用
```

### 5.2 グリーンボンド連携

| 項目 | 仕様 |
|------|------|
| 対象 | ESGトランジションにより切り替えた車両ポートフォリオ |
| フレームワーク | ICMA グリーンボンド原則2021準拠 |
| 適格基準 | CO2排出量が旧車両比30%以上削減される車両入替案件 |
| レポーティング | 年次インパクトレポート自動生成 |
| 外部認証 | 第三者認証（セカンドオピニオン）対応データ出力 |

### 5.3 CO2排出削減量の計算・レポート

#### 5.3.1 計算式

```
# 車両単位の年間CO2排出量
annual_co2_kg = annual_fuel_consumption_l × emission_factor_kg_per_l

# 排出係数（環境省公表値ベース）
emission_factors = {
    "diesel":   2.5858,  # kg-CO2/L
    "gasoline": 2.3166,  # kg-CO2/L
    "lng":      2.2264,  # kg-CO2/Nm3
    "ev":       0.0      # 走行時ゼロ（Scope 2は別途）
}

# ポートフォリオ全体の削減量
portfolio_co2_reduction = Σ(old_vehicle_co2 - new_vehicle_co2)  for each transition
```

#### 5.3.2 レポート出力項目

| レポート項目 | 単位 | 算出方法 |
|-------------|------|---------|
| ポートフォリオ総CO2排出量 | t-CO2/年 | 全車両の年間排出量合計 |
| トランジション後CO2削減量 | t-CO2/年 | 切替前後の差分合計 |
| 削減率 | % | 削減量/切替前排出量 |
| 車両1台あたり平均削減量 | t-CO2/年/台 | 削減量/切替台数 |
| 燃料コスト削減額 | 万円/年 | 燃料消費量差分 × 燃料単価 |
| カーボンクレジット換算額 | 万円/年 | 削減量 × J-クレジット市場価格 |

---

## 6. 予知保全連携

### 6.1 DTCコード分析による故障予測

#### 6.1.1 DTCコード分類と重要度

| DTC分類 | パターン | 重要度 | 資産価値への影響 |
|---------|---------|--------|----------------|
| パワートレイン重大 | P0xxx (一部) | Critical | health_score × 0.3 |
| パワートレイン軽微 | P0xxx (一般) | Warning | health_score × 0.7 |
| 排ガス系 | P04xx | Warning | health_score × 0.8 |
| ボディ系 | B0xxx | Info | health_score × 0.95 |
| シャシー系 | C0xxx | Warning | health_score × 0.8 |
| ネットワーク系 | U0xxx | Info | health_score × 0.95 |

#### 6.1.2 故障予測モデル

Phase 3bの初期段階ではルールベース、Phase 4以降でML（機械学習）モデルへの移行を想定する。

**ルールベース（Phase 3b）:**

```python
def predict_failure_risk(vehicle_telemetry_history: list) -> dict:
    risk_indicators = {
        "engine": evaluate_engine_risk(
            dtc_frequency_30d,
            coolant_temp_trend,
            oil_temp_trend,
            rpm_stability
        ),
        "dpf": evaluate_dpf_risk(
            soot_accumulation_rate,
            regen_frequency,
            exhaust_temp_trend
        ),
        "battery": evaluate_battery_risk(
            voltage_trend_30d,
            cold_start_voltage_min
        ),
        "transmission": evaluate_transmission_risk(
            dtc_codes_filtered,
            shift_pattern_anomaly
        )
    }
    return {
        "overall_risk": weighted_average(risk_indicators),
        "components": risk_indicators,
        "recommended_actions": generate_recommendations(risk_indicators)
    }
```

### 6.2 メンテナンス推奨スケジュールの自動生成

テレメトリーデータに基づき、従来の距離/期間ベースの定期メンテナンスを、状態ベース（CBM: Condition-Based Maintenance）に進化させる。

| メンテナンス項目 | 従来トリガー | CBMトリガー（テレメトリー活用） |
|----------------|------------|-------------------------------|
| エンジンオイル交換 | 20,000km毎 | オイル劣化推定値 + 稼働時間 + 温度履歴 |
| DPFクリーニング | 100,000km毎 | すす蓄積率80%到達予測日 |
| バッテリー交換 | 3年毎 | 電圧低下トレンドが閾値到達予測日 |
| ブレーキパッド交換 | 60,000km毎 | 制動パターン分析 + 走行距離ペース |
| クーラント交換 | 2年毎 | 冷却水温安定性の経時変化 |

### 6.3 車両状態スコアの資産価値への反映

`telemetry_health_score` は日次で再計算され、`depreciation_curves` テーブルの `custom_curve_json` に補正値として反映される。

```
# 実効残価率（テレメトリー補正後）
effective_residual_rate = base_residual_rate × telemetry_health_score × mileage_pace_factor

# 例：基本残価率55%、ヘルススコア0.92、走行ペース係数0.97の場合
# effective_residual_rate = 0.55 × 0.92 × 0.97 = 0.4907 (49.07%)
```

---

## 7. 投資家向けレポーティング

ピッチデッキの「Investors --- 高い回復力を持つオルタナティブ資産クラス」ビジョンに対応する機能。

### 7.1 ポートフォリオダッシュボード（リアルタイム）

| KPI | 算出方法 | 更新頻度 |
|-----|---------|---------|
| ポートフォリオ総資産価値 | Σ(dynamic_asset_value) for all active leases | 1時間毎 |
| 加重平均ヘルススコア | Σ(health_score × asset_value) / Σ(asset_value) | 日次 |
| LTV分布 | 各車両のLTVをヒストグラム化 | 日次 |
| 異常検知件数（直近30日） | telemetry_alertsの件数集計 | リアルタイム |
| ESGスコア | ポートフォリオのCO2排出量原単位 | 月次 |
| 予想損失率（EL） | デフォルト確率 × LGD × EAD | 日次 |

### 7.2 レポート自動生成

| レポート種別 | 頻度 | 形式 | 配信方法 |
|-------------|------|------|---------|
| ポートフォリオ月次レポート | 月次 | PDF | メール自動送信 |
| ESGインパクトレポート | 四半期 | PDF | メール + ダウンロード |
| 異常検知サマリー | 週次 | メール本文 | メール自動送信 |
| 車両状態一覧 | 日次 | CSVダウンロード | ダッシュボードからDL |

---

## 8. データベース設計（追加テーブル）

既存のSupabaseスキーマに以下のテーブルを追加する。`gen_random_uuid()` と `set_updated_at()` トリガーは既存の共通関数を使用する。

### 8.1 vehicle_telemetry テーブル

車両から受信したテレメトリーデータの生データ格納。

```sql
-- ============================================================================
-- Migration: 2026XXXX000001_create_vehicle_telemetry
-- Description: Create vehicle_telemetry table for raw telemetry data
-- ============================================================================

CREATE TABLE public.vehicle_telemetry (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id            uuid        NOT NULL REFERENCES public.vehicles(id),
  device_id             text        NOT NULL,
  recorded_at           timestamptz NOT NULL,
  odometer_km           integer,
  engine_hours          integer,
  fuel_consumption_total_l  numeric(12,2),
  fuel_rate_lph         numeric(6,2),
  coolant_temp_c        numeric(5,1),
  oil_temp_c            numeric(5,1),
  rpm                   integer,
  battery_voltage       numeric(4,1),
  dpf_soot_pct          numeric(5,2),
  gps_lat               numeric(10,7),
  gps_lng               numeric(10,7),
  gps_speed_kmh         numeric(5,1),
  dtc_codes             jsonb       DEFAULT '[]'::jsonb,
  raw_payload           jsonb,
  created_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.vehicle_telemetry
  IS 'Raw telemetry data received from vehicle OBD-II/telematics devices';

-- パーティショニング用（将来的にrecorded_atでレンジパーティション化を検討）
CREATE INDEX idx_telemetry_vehicle_recorded
  ON public.vehicle_telemetry (vehicle_id, recorded_at DESC);

CREATE INDEX idx_telemetry_device_id
  ON public.vehicle_telemetry (device_id);

CREATE INDEX idx_telemetry_recorded_at
  ON public.vehicle_telemetry (recorded_at DESC);

-- DTCコードが存在するレコードのみの部分インデックス
CREATE INDEX idx_telemetry_with_dtc
  ON public.vehicle_telemetry (vehicle_id, recorded_at DESC)
  WHERE dtc_codes != '[]'::jsonb;
```

### 8.2 telemetry_alerts テーブル

異常検知の結果とLTV再計算トリガーの記録。

```sql
-- ============================================================================
-- Migration: 2026XXXX000002_create_telemetry_alerts
-- Description: Create telemetry_alerts table for anomaly detection events
-- ============================================================================

CREATE TABLE public.telemetry_alerts (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id            uuid        NOT NULL REFERENCES public.vehicles(id),
  telemetry_id          uuid        REFERENCES public.vehicle_telemetry(id),
  alert_type            text        NOT NULL
                                    CHECK (alert_type IN (
                                      'mileage_spike',
                                      'engine_critical_dtc',
                                      'coolant_temp_high',
                                      'battery_low',
                                      'dpf_overload',
                                      'prolonged_idle',
                                      'gps_anomaly',
                                      'health_score_drop'
                                    )),
  severity              text        NOT NULL DEFAULT 'medium'
                                    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  title                 text        NOT NULL,
  description           text,
  alert_data            jsonb,
  health_score_before   numeric(4,3),
  health_score_after    numeric(4,3),
  ltv_before            numeric(6,4),
  ltv_after             numeric(6,4),
  ltv_recalculated      boolean     NOT NULL DEFAULT false,
  acknowledged_at       timestamptz,
  acknowledged_by       uuid        REFERENCES public.users(id),
  resolved_at           timestamptz,
  resolved_by           uuid        REFERENCES public.users(id),
  resolution_note       text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.telemetry_alerts
  IS 'Anomaly detection alerts triggered by vehicle telemetry analysis';

CREATE INDEX idx_alerts_vehicle_id      ON public.telemetry_alerts (vehicle_id);
CREATE INDEX idx_alerts_type            ON public.telemetry_alerts (alert_type);
CREATE INDEX idx_alerts_severity        ON public.telemetry_alerts (severity);
CREATE INDEX idx_alerts_created_at      ON public.telemetry_alerts (created_at DESC);
CREATE INDEX idx_alerts_unacknowledged  ON public.telemetry_alerts (created_at DESC)
  WHERE acknowledged_at IS NULL;

-- Trigger
CREATE TRIGGER trg_telemetry_alerts_updated_at
  BEFORE UPDATE ON public.telemetry_alerts
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
```

### 8.3 esg_metrics テーブル

ESG関連メトリクスの車両単位・ポートフォリオ単位の記録。

```sql
-- ============================================================================
-- Migration: 2026XXXX000003_create_esg_metrics
-- Description: Create esg_metrics table for ESG tracking and reporting
-- ============================================================================

CREATE TABLE public.esg_metrics (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id            uuid        NOT NULL REFERENCES public.vehicles(id),
  period_start          date        NOT NULL,
  period_end            date        NOT NULL,
  fuel_type             text        NOT NULL
                                    CHECK (fuel_type IN ('diesel', 'gasoline', 'lng', 'ev', 'hybrid')),
  fuel_consumed_l       numeric(10,2),
  distance_km           integer,
  fuel_efficiency_km_per_l  numeric(6,2),
  co2_emission_kg       numeric(10,2),
  co2_emission_factor   numeric(6,4),
  is_transition_vehicle boolean     NOT NULL DEFAULT false,
  replaced_vehicle_id   uuid        REFERENCES public.vehicles(id),
  co2_reduction_kg      numeric(10,2),
  transition_score      numeric(4,3),
  green_bond_eligible   boolean     NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_esg_period
    CHECK (period_end > period_start),
  CONSTRAINT uq_esg_vehicle_period
    UNIQUE (vehicle_id, period_start, period_end)
);

COMMENT ON TABLE public.esg_metrics
  IS 'ESG metrics per vehicle per period for transition tracking and green bond reporting';

CREATE INDEX idx_esg_vehicle_id         ON public.esg_metrics (vehicle_id);
CREATE INDEX idx_esg_period             ON public.esg_metrics (period_start, period_end);
CREATE INDEX idx_esg_transition         ON public.esg_metrics (is_transition_vehicle)
  WHERE is_transition_vehicle = true;
CREATE INDEX idx_esg_green_bond         ON public.esg_metrics (green_bond_eligible)
  WHERE green_bond_eligible = true;

-- Trigger
CREATE TRIGGER trg_esg_metrics_updated_at
  BEFORE UPDATE ON public.esg_metrics
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();
```

### 8.4 vehicle_health_scores テーブル

日次で計算される車両ヘルススコアの履歴管理。

```sql
-- ============================================================================
-- Migration: 2026XXXX000004_create_vehicle_health_scores
-- Description: Create vehicle_health_scores table for daily health tracking
-- ============================================================================

CREATE TABLE public.vehicle_health_scores (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  vehicle_id            uuid        NOT NULL REFERENCES public.vehicles(id),
  score_date            date        NOT NULL,
  overall_score         numeric(4,3) NOT NULL CHECK (overall_score >= 0 AND overall_score <= 1),
  engine_score          numeric(4,3),
  coolant_score         numeric(4,3),
  oil_temp_score        numeric(4,3),
  dpf_score             numeric(4,3),
  battery_score         numeric(4,3),
  idle_ratio_score      numeric(4,3),
  harsh_driving_score   numeric(4,3),
  mileage_pace_factor   numeric(5,3),
  dynamic_asset_value_yen bigint,
  effective_residual_rate numeric(5,4),
  score_details_json    jsonb,
  created_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_health_vehicle_date UNIQUE (vehicle_id, score_date)
);

COMMENT ON TABLE public.vehicle_health_scores
  IS 'Daily computed health scores and dynamic asset valuations per vehicle';

CREATE INDEX idx_health_vehicle_date
  ON public.vehicle_health_scores (vehicle_id, score_date DESC);
```

### 8.5 ER図（追加テーブル間の関係）

```
                    ┌──────────────────┐
                    │    vehicles      │ ← 既存テーブル
                    │    (既存)         │
                    └──┬───┬───┬───┬──┘
                       │   │   │   │
          ┌────────────┘   │   │   └────────────────┐
          │                │   │                     │
          ▼                ▼   ▼                     ▼
┌──────────────────┐ ┌──────────────┐  ┌──────────────────────┐
│vehicle_telemetry │ │telemetry_    │  │  esg_metrics         │
│                  │ │alerts        │  │                      │
│ vehicle_id (FK)  │ │vehicle_id(FK)│  │  vehicle_id (FK)     │
│ device_id        │ │telemetry_id  │  │  replaced_vehicle_id │
│ recorded_at      │ │  (FK)        │  │  co2_emission_kg     │
│ odometer_km      │ │alert_type    │  │  transition_score    │
│ engine_hours     │ │severity      │  │  green_bond_eligible │
│ dtc_codes        │ │ltv_before    │  └──────────────────────┘
│ gps_lat/lng      │ │ltv_after     │
│ ...              │ │...           │
└────────┬─────────┘ └──────────────┘
         │
         │ telemetry_id (FK)
         ▼
┌──────────────────────┐
│vehicle_health_scores │
│                      │
│ vehicle_id (FK)      │
│ score_date           │
│ overall_score        │
│ dynamic_asset_value  │
│ ...                  │
└──────────────────────┘
```

---

## 9. APIエンドポイント

既存の `/api/v1/` 名前空間に以下のエンドポイントを追加する。認証はSupabase Auth JWTトークンを使用（既存方式を踏襲）。

### 9.1 テレメトリーデータ受信

#### `POST /api/v1/telemetry/ingest`

テレマティクスデバイスまたはベンダーシステムからのテレメトリーデータを受信する。

| 項目 | 値 |
|------|-----|
| 認証 | API Key（デバイス認証用。ユーザーJWTとは別管理） |
| Content-Type | application/json |
| レート制限 | 1,000 req/min（デバイス単位） |

**リクエストボディ:**

```json
{
  "device_id": "DEV-20260101-0001",
  "vehicle_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-04-06T10:30:00+09:00",
  "data": {
    "odometer_km": 245320,
    "engine_hours": 8420,
    "fuel_consumption_total_l": 98210.5,
    "fuel_rate_lph": 12.3,
    "coolant_temp_c": 92.1,
    "oil_temp_c": 105.3,
    "rpm": 1850,
    "battery_voltage": 26.4,
    "dpf_soot_pct": 35.2,
    "gps": {
      "lat": 35.6812,
      "lng": 139.7671,
      "speed_kmh": 65.2
    },
    "dtc_codes": []
  }
}
```

**レスポンス（成功）:**

```json
{
  "status": "ok",
  "data": {
    "telemetry_id": "a1b2c3d4-...",
    "processed_at": "2026-04-06T10:30:01+09:00",
    "alerts_generated": 0
  }
}
```

**レスポンス（異常検知時）:**

```json
{
  "status": "ok",
  "data": {
    "telemetry_id": "a1b2c3d4-...",
    "processed_at": "2026-04-06T10:30:01+09:00",
    "alerts_generated": 1,
    "alerts": [
      {
        "alert_id": "e5f6g7h8-...",
        "alert_type": "coolant_temp_high",
        "severity": "high",
        "title": "冷却水温異常検知"
      }
    ]
  }
}
```

#### `POST /api/v1/telemetry/ingest/batch`

複数レコードの一括受信（オフライン期間後の同期用）。

| 項目 | 値 |
|------|-----|
| 最大レコード数 | 1,000件/リクエスト |
| タイムアウト | 30秒 |

### 9.2 テレメトリーステータス照会

#### `GET /api/v1/telemetry/{vehicle_id}/status`

指定車両の最新テレメトリーステータスを取得する。

| 項目 | 値 |
|------|-----|
| 認証 | Supabase Auth JWT |
| 権限 | 営業担当者以上 |

**レスポンス:**

```json
{
  "status": "ok",
  "data": {
    "vehicle_id": "550e8400-...",
    "last_received_at": "2026-04-06T10:30:00+09:00",
    "device_status": "online",
    "current": {
      "odometer_km": 245320,
      "engine_hours": 8420,
      "fuel_efficiency_km_per_l": 3.8,
      "gps": { "lat": 35.6812, "lng": 139.7671 }
    },
    "health_score": {
      "overall": 0.921,
      "engine": 0.95,
      "dpf": 0.88,
      "battery": 0.93,
      "updated_at": "2026-04-06T00:00:00+09:00"
    },
    "mileage_pace": {
      "contractual_annual_km": 60000,
      "actual_pace_annual_km": 58200,
      "pace_ratio": 0.97,
      "pace_factor": 1.0015
    },
    "dynamic_asset_value_yen": 5420000,
    "active_alerts_count": 0
  }
}
```

#### `GET /api/v1/telemetry/{vehicle_id}/history`

テレメトリーデータの時系列履歴を取得する。

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| from | datetime | Yes | 取得開始日時 |
| to | datetime | Yes | 取得終了日時 |
| resolution | string | No | `raw`, `hourly`, `daily`（デフォルト: `hourly`） |
| fields | string | No | カンマ区切りの取得フィールド指定 |

#### `GET /api/v1/telemetry/{vehicle_id}/alerts`

指定車両の異常検知アラート一覧を取得する。

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| severity | string | No | `low`, `medium`, `high`, `critical` |
| status | string | No | `open`, `acknowledged`, `resolved` |
| limit | integer | No | 取得件数（デフォルト: 50、最大: 200） |
| offset | integer | No | オフセット |

### 9.3 ESGメトリクス

#### `GET /api/v1/esg/portfolio-impact`

ポートフォリオ全体のESGインパクトサマリーを取得する。

| 項目 | 値 |
|------|-----|
| 認証 | Supabase Auth JWT |
| 権限 | ファンドマネージャー以上 |

**レスポンス:**

```json
{
  "status": "ok",
  "data": {
    "period": {
      "from": "2026-01-01",
      "to": "2026-03-31"
    },
    "portfolio_summary": {
      "total_vehicles": 142,
      "diesel_vehicles": 98,
      "high_efficiency_vehicles": 44,
      "transition_in_progress": 8
    },
    "emissions": {
      "total_co2_tonnes": 1842.5,
      "co2_per_vehicle_tonnes": 12.97,
      "co2_reduction_from_transitions_tonnes": 156.3,
      "reduction_rate_pct": 7.82
    },
    "fuel_efficiency": {
      "fleet_avg_km_per_l": 3.62,
      "diesel_avg_km_per_l": 3.41,
      "efficient_avg_km_per_l": 4.12,
      "improvement_pct": 20.82
    },
    "green_bond": {
      "eligible_vehicles": 36,
      "eligible_asset_value_yen": 248000000,
      "cumulative_co2_reduction_tonnes": 412.8
    },
    "transition_candidates": {
      "count": 22,
      "avg_transition_score": 0.78,
      "estimated_annual_co2_reduction_tonnes": 198.4
    }
  }
}
```

#### `GET /api/v1/esg/vehicle/{vehicle_id}/metrics`

個別車両のESGメトリクスを取得する。

#### `GET /api/v1/esg/report/generate`

ESGインパクトレポートのPDFを生成する。

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| period_from | date | Yes | レポート対象期間（開始） |
| period_to | date | Yes | レポート対象期間（終了） |
| format | string | No | `pdf`, `csv`（デフォルト: `pdf`） |

### 9.4 ダイナミックプライシング

#### `GET /api/v1/pricing/dynamic/{vehicle_id}`

テレメトリー補正後のリアルタイム資産評価を取得する。

**レスポンス:**

```json
{
  "status": "ok",
  "data": {
    "vehicle_id": "550e8400-...",
    "valuation_timestamp": "2026-04-06T10:35:00+09:00",
    "static_valuation": {
      "base_market_price_yen": 6200000,
      "condition_factor": 0.85,
      "trend_factor": 1.02,
      "safety_margin_rate": 0.10,
      "static_value_yen": 4838940
    },
    "telemetry_adjustment": {
      "health_score": 0.921,
      "mileage_pace_factor": 0.97,
      "combined_factor": 0.893
    },
    "dynamic_value_yen": 4321195,
    "delta_from_static_yen": -517745,
    "delta_pct": -10.7,
    "ltv_current": 0.72,
    "ltv_threshold": 0.85,
    "ltv_status": "healthy"
  }
}
```

### 9.5 予知保全

#### `GET /api/v1/maintenance/{vehicle_id}/schedule`

テレメトリーベースのメンテナンス推奨スケジュールを取得する。

#### `GET /api/v1/maintenance/{vehicle_id}/predictions`

故障予測結果を取得する。

### 9.6 APIエンドポイント一覧

| メソッド | パス | 説明 | Phase |
|---------|------|------|-------|
| `POST` | `/api/v1/telemetry/ingest` | テレメトリーデータ受信 | 3a |
| `POST` | `/api/v1/telemetry/ingest/batch` | テレメトリーデータ一括受信 | 3a |
| `GET` | `/api/v1/telemetry/{vehicle_id}/status` | 最新テレメトリーステータス | 3a |
| `GET` | `/api/v1/telemetry/{vehicle_id}/history` | テレメトリー時系列履歴 | 3a |
| `GET` | `/api/v1/telemetry/{vehicle_id}/alerts` | アラート一覧 | 3b |
| `GET` | `/api/v1/pricing/dynamic/{vehicle_id}` | 動的資産評価 | 3b |
| `GET` | `/api/v1/maintenance/{vehicle_id}/schedule` | メンテナンス推奨 | 3b |
| `GET` | `/api/v1/maintenance/{vehicle_id}/predictions` | 故障予測 | 3b |
| `GET` | `/api/v1/esg/portfolio-impact` | ESGポートフォリオサマリー | 3c |
| `GET` | `/api/v1/esg/vehicle/{vehicle_id}/metrics` | 車両別ESGメトリクス | 3c |
| `GET` | `/api/v1/esg/report/generate` | ESGレポート生成 | 3c |

---

## 10. セキュリティ要件

### 10.1 デバイス認証

| 項目 | 仕様 |
|------|------|
| 認証方式 | API Key + デバイス証明書（mTLS推奨） |
| API Key管理 | デバイスごとに一意のキーを発行、Supabase Vault で暗号化保管 |
| ローテーション | 90日ごとの自動ローテーション |
| 失効処理 | 盗難・紛失時の即時失効API |

### 10.2 データ保護

| データ区分 | 保護要件 |
|-----------|---------|
| GPS位置情報 | 個人情報保護法上の「個人関連情報」。アクセス権限を厳格に管理 |
| テレメトリー生データ | RLSにより車両所有者・担当者のみアクセス可 |
| ESGメトリクス | ファンドマネージャー以上のロールに限定 |
| 投資家レポート | 個別車両の特定につながる情報を匿名化 |

### 10.3 RLSポリシー（追加）

```sql
-- vehicle_telemetry: 担当車両のデータのみ閲覧可
ALTER TABLE public.vehicle_telemetry ENABLE ROW LEVEL SECURITY;

CREATE POLICY telemetry_select_policy ON public.vehicle_telemetry
  FOR SELECT USING (
    vehicle_id IN (
      SELECT v.id FROM public.vehicles v
      JOIN public.simulations s ON s.target_model_name = v.model_name
      WHERE s.user_id = auth.uid()
    )
    OR auth.jwt() ->> 'role' IN ('fund_manager', 'admin')
  );

-- telemetry_alerts: 同上
ALTER TABLE public.telemetry_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY alerts_select_policy ON public.telemetry_alerts
  FOR SELECT USING (
    vehicle_id IN (
      SELECT v.id FROM public.vehicles v
      JOIN public.simulations s ON s.target_model_name = v.model_name
      WHERE s.user_id = auth.uid()
    )
    OR auth.jwt() ->> 'role' IN ('fund_manager', 'admin')
  );
```

---

## 11. 非機能要件

### 11.1 パフォーマンス要件

| 項目 | 要件 |
|------|------|
| テレメトリー受信スループット | 10,000 msg/sec（初期想定車両数500台、各デバイス1msg/min） |
| Ingest APIレイテンシ | p99 < 200ms |
| ステータスAPI レイテンシ | p99 < 500ms |
| ダイナミックプライシング計算 | p99 < 1,000ms |
| 異常検知レイテンシ | データ受信から5秒以内にアラート生成 |
| 日次ヘルススコア計算バッチ | 500台を30分以内に完了 |

### 11.2 可用性・信頼性

| 項目 | 要件 |
|------|------|
| Ingest APIの可用性 | 99.9%（月間ダウンタイム43分以内） |
| データ欠損許容 | テレメトリーデータの欠損率 < 0.1% |
| バックフィル | デバイスオフライン復帰後、batch APIで欠損データを補完 |
| 障害時のグレースフル劣化 | テレメトリー障害時は最新の静的評価にフォールバック |

### 11.3 スケーラビリティ

| フェーズ | 想定車両台数 | テレメトリー日次データ量 |
|---------|------------|----------------------|
| Phase 3a（初期） | 50台 | 約72,000レコード/日 |
| Phase 3b（拡張） | 200台 | 約288,000レコード/日 |
| Phase 3c（本格運用） | 500台 | 約720,000レコード/日 |
| Phase 4（将来） | 2,000台 | 約2,880,000レコード/日 |

Phase 4以降のスケーリング対応として、`vehicle_telemetry` テーブルの `recorded_at` によるレンジパーティショニング、およびTimescaleDB拡張の導入を検討する。

---

*本仕様書はPhase 3+の将来構想を記述したものであり、実装着手前に関係者レビューおよび技術検証（PoC）を実施する。*
