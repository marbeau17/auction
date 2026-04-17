# CVLPOS 仕様変更書（第2版）— 変更要求仕様書

**文書番号:** CR-CVLPOS-2026-002
**作成日:** 2026-04-10
**ステータス:** レビュー中
**対象システム:** CVLPOS（商用車リースバック価格最適化システム）

---

## 1. エグゼクティブサマリー

### 1.1 変更の背景
当初想定の4者間スキーム（SPC / Operator / Investor / End User）から、実際のファンド組成（カーチスファンド15号等）を前提とした**多重契約・複数ステークホルダーモデル**への拡張が必要となった。

### 1.2 変更の目的
CVLPOSを以下の3本柱を持つ**基幹システム**として再定義する：

1. **統合プライシング・エンジン** — 買取価格・残価・リース料の3価格連動算出
2. **契約・ドキュメント自動化** — 9種類の契約書自動生成 + 提案書PDF出力
3. **請求・配信管理** — 月次請求書自動生成・承認・メール送付ワークフロー

### 1.3 現行システムとのギャップ分析

| 領域 | 現行 (As-Is) | 要求 (To-Be) | ギャップレベル |
|------|-------------|-------------|-------------|
| ステークホルダー | 6ロール (spc/operator/investor/end_user/guarantor/trustee) | 8ロール (+private_placement_agent, +asset_manager, +accounting_firm, +accounting_delegate) | 中 |
| プライシング | 単一PricingEngine (買取→リース一体) | 3ステップ連動 (買取→残価→リース) + パラメータマスタ | 大 |
| 契約書 | 4テンプレート (TK/Sales/MasterLease/SubLease) | 9テンプレート (+私募取扱/顧客紹介/AM/会計①②) | 大 |
| 提案書 | なし | PDF出力 + NAV曲線シミュレーション | 新規 |
| 請求管理 | lease_payments テーブルのみ | 請求書生成→承認→PDF→メール送付 | 大 |
| ダッシュボード | 基本KPI 3項目 | 運用台数/総投資額/利益転換/請求入金ステータス | 中 |
| RBAC | 3ロール (admin/sales/viewer) | 8ステークホルダー別権限分離 | 大 |
| 相場インポート | スクレイピング (Playwright) | + CSV/Excel手動インポート | 小 |

---

## 2. ステークホルダー別ディスカッションポイント

### 2.1 ソフトウェアエンジニアリングチーム向け

**アーキテクチャ決定事項:**

1. **プライシングエンジンの分離設計**
   - 現行 `PricingEngine` クラス (1,367行) をリファクタリング
   - 3つの独立した計算モジュールに分離:
     - `AcquisitionPriceCalculator` — 適正買取価格算出
     - `ResidualValueCalculator` — 残価/エグジット価格算出（既存を拡張）
     - `LeasePriceCalculator` — 適正リース料算出（ステークホルダー利回り加味）
   - `IntegratedPricingEngine` がオーケストレーション

2. **データベーススキーマ変更**
   - 新テーブル: `pricing_masters`, `pricing_parameters`, `invoices`, `invoice_line_items`, `invoice_approvals`, `email_logs`
   - 既存テーブル拡張: `deal_stakeholders` (role_type 追加), `contract_templates` (5件追加シード)
   - `users` テーブルに `stakeholder_role` カラム追加

3. **RBAC拡張**
   - 現行3ロール → ステークホルダー8タイプ別権限マトリクス
   - 価格算出ロジック: 社内のみ閲覧可 (operator/admin)
   - 契約書: 当事者のみ閲覧可
   - 請求書: 発行者 + 請求先のみ

4. **技術的リスク**
   - PricingEngineリファクタリング時の後方互換性
   - 既存シミュレーション結果への影響（マイグレーション必要）
   - DOCX テンプレート変数マッピングの複雑性

**推奨アプローチ:**
- Feature flag で段階的リリース
- 既存 `PricingEngine.run_simulation()` は維持し、新エンジンは別エントリポイント
- 既存テストを全てパスさせながら新機能を追加

### 2.2 マーケティングチーム向け

**提案書PDF機能の要件:**
- ブランディング: カーチスロゴ、カラーパレット統一
- コンテンツ: 3価格シミュレーション結果、NAV曲線グラフ、損益分岐点分析
- 配布: 運送事業者との商談資料として使用
- 差別化ポイント: 「データに基づく適正価格」の透明性を訴求

**ダッシュボードKPI:**
- 運用台数推移 → 成長率の可視化
- 総投資額 → ファンド規模の拡大傾向
- 利益転換状況 → 各ファンドの健全性

### 2.3 プロダクトマネージャー向け

**Epic優先度マトリクス:**

| Epic | ビジネスインパクト | 技術難度 | 優先度 | 推奨フェーズ |
|------|-----------------|---------|-------|------------|
| Epic 1: 統合プライシング | 最高 | 高 | P0 | Phase 1 |
| Epic 3: 契約書9種類 | 高 | 中 | P0 | Phase 1 |
| Epic 2: 提案書PDF | 高 | 中 | P1 | Phase 1 |
| Epic 5: 相場インポート | 中 | 低 | P1 | Phase 1 |
| Epic 4: インベントリ管理 | 中 | 中 | P1 | Phase 2 |
| Epic 6: 請求管理 | 高 | 高 | P1 | Phase 2 |
| Epic 7: ダッシュボード | 中 | 低 | P2 | Phase 2 |

**依存関係:**
```
Epic 5 (相場データ) → Epic 1 (プライシング) → Epic 2 (提案書)
                                              → Epic 3 (契約書)
                                              → Epic 6 (請求管理)
Epic 4 (インベントリ) → Epic 7 (ダッシュボード)
```

**受け入れ基準 (全Epic共通):**
- 既存機能の回帰テストが全てパス
- 新機能のユニットテストカバレッジ 80%以上
- RLS ポリシーが正しく適用されていること
- レスポンスタイム: 価格算出 < 2秒、PDF生成 < 5秒

### 2.4 ファンドマネージャー向け

**プライシング精度の検証ポイント:**

1. **買取価格 (Step 1)**
   - オークション相場データの信頼性（データソース、サンプル数）
   - 年式・走行距離の重み付けの妥当性
   - 安全マージンの適正値（現行 3-20%）

2. **残価 (Step 2)**
   - 減価償却カーブの妥当性（定率法200% vs 実態）
   - ボディタイプ別の残存率テーブルの精度
   - 市場変動リスクの織り込み方

3. **リース料 (Step 3) — 新規追加要素**
   - 投資家配当率（例: 年8%）
   - AM報酬率（例: 年2%）
   - 私募取扱報酬率（例: 一括3%）
   - 会計事務委託料（例: 月額固定）
   - カーチスマージン
   - **損益分岐点（BEP）の算出ロジック**

4. **NAV曲線シミュレーション**
   - 月次の資産価値推移
   - 利益転換点（累積利益 > 0 となる月）
   - エグジット時の残価回収シナリオ（Bull/Base/Bear）

---

## 3. 技術仕様 — Epic別詳細

### Epic 1: 統合プライシング・エンジン

#### 3.1.1 新規モジュール構成

```
app/core/
├── pricing.py                    # 既存（後方互換維持）
├── integrated_pricing.py         # NEW: オーケストレーター
├── acquisition_price.py          # NEW: Step 1 買取価格算出
├── residual_value.py             # 既存（Step 2 拡張）
├── lease_price.py                # NEW: Step 3 リース料算出
├── nav_calculator.py             # NEW: NAV曲線・損益分岐計算
└── pricing_constants.py          # NEW: 定数・パラメータ集約
```

#### 3.1.2 データモデル

```python
# 新規 Pydantic モデル
class PricingMasterInput(BaseModel):
    """相場データ・減価償却パラメータ・目標利回り"""
    auction_data_source: str          # CSV/Excel ファイル参照
    depreciation_method: str          # "declining_200" | "straight_line"
    investor_yield_rate: float        # 投資家要求利回り (年率)
    am_fee_rate: float                # AM報酬率 (年率)
    placement_fee_rate: float         # 私募取扱報酬率 (一括)
    accounting_fee_monthly: int       # 会計事務委託月額 (円)
    operator_margin_rate: float       # カーチスマージン率
    safety_margin_rate: float         # 安全マージン率

class IntegratedPricingResult(BaseModel):
    """3価格連動算出結果"""
    # Step 1
    acquisition_price: int
    acquisition_price_breakdown: dict
    # Step 2
    residual_value: int
    residual_rate: float
    residual_scenarios: dict          # bull/base/bear
    # Step 3
    monthly_lease_fee: int
    annual_lease_fee: int
    lease_fee_breakdown: dict         # 各ステークホルダー取り分
    breakeven_month: int
    # NAV
    nav_curve: list[dict]             # [{month, nav, cumulative_income, ...}]
    profit_conversion_month: int      # 利益転換月
```

#### 3.1.3 計算ロジック詳細

**Step 1: 適正買取価格**
```
適正買取価格 = 市場相場中央値 × トレンド係数 × (1 - 安全マージン)
              + ボディオプション調整額

市場相場中央値 = weighted_median(auction_data, weights=[年式近接度, 走行距離近接度])
トレンド係数 = clamp(直近6ヶ月の価格変動率, 0.80, 1.20)
安全マージン = base_margin + volatility_premium × 価格標準偏差 / 中央値
```

**Step 2: 適正残価（エグジット価格）**
```
残価 = 買取価格 × 残存率(リース期間, ボディタイプ) × 走行距離調整係数

残存率 = body_retention_table[body_type][lease_years]
走行距離調整係数 = f(予想走行距離 vs 標準走行距離)

シナリオ分析:
  Bull: 残価 × 1.15
  Base: 残価 × 1.00
  Bear: 残価 × 0.85
```

**Step 3: 適正リース料**
```
月額リース料 = (償却元本 + 総コスト) / リース月数

償却元本 = 買取価格 - 残価
総コスト = 投資家配当 + AM報酬 + 私募取扱報酬(月額按分) + 会計費用 + マージン

投資家配当(月額) = 買取価格 × investor_yield_rate / 12
AM報酬(月額) = 買取価格 × am_fee_rate / 12
私募取扱(月額按分) = 買取価格 × placement_fee_rate / lease_months
会計費用(月額) = accounting_fee_monthly
マージン(月額) = 償却元本 × operator_margin_rate / lease_months

損益分岐月 = 累積リース収入 > 買取価格 - 残価 + 累積コスト となる最初の月
```

### Epic 2: 提案書・シミュレーション

#### 3.2.1 提案書PDF構成

```
1ページ: 表紙（ファンド名、日付、ロゴ）
2ページ: エグゼクティブサマリー（3価格要約）
3ページ: 車両情報・市場分析
4ページ: プライシング詳細（Step 1-3 内訳）
5ページ: NAV曲線グラフ + 損益分岐分析
6ページ: シナリオ分析（Bull/Base/Bear）
7ページ: 注意事項・免責
```

#### 3.2.2 技術実装

```python
# PDF生成ライブラリ: ReportLab or WeasyPrint
# グラフ生成: matplotlib (サーバーサイド)
# テンプレート: Jinja2 HTML → PDF変換

class ProposalGenerator:
    def generate(self, pricing_result: IntegratedPricingResult,
                 vehicle_info: VehicleBase,
                 fund_info: dict) -> bytes:  # PDF bytes
```

### Epic 3: 契約書・ドキュメント管理

#### 3.3.1 9種類の契約書テンプレート

| # | 契約書名 | 当事者A | 当事者B | 自動流し込みパラメータ |
|---|---------|--------|--------|-------------------|
| 1 | 匿名組合契約書 | SPC | 投資家 | 投資額、配当率、運用期間 |
| 2 | 私募取扱業務契約書 | SPC | 私募取扱業者 | 取扱報酬率、取扱金額 |
| 3 | 顧客紹介業務契約書 | SPC | AM会社 | 紹介報酬率 |
| 4 | アセットマネジメント契約書 | SPC | AM会社 | AM報酬率、管理対象資産 |
| 5 | 会計事務委託契約書① | SPC | 会計事務所 | 月額報酬、委託範囲 |
| 6 | 会計事務委託契約書② | SPC | 一般社団法人 | 月額報酬、委託範囲 |
| 7 | マスターリース契約書 | SPC | カーチスロジテック | リース料、期間、車両一覧 |
| 8 | サブリース契約書 | カーチスロジテック | 運送会社 | サブリース料、期間 |
| 9 | 車両売買契約書 | 運送会社⇔SPC | - | 買取価格、車両情報 |

#### 3.3.2 設計書エクスポート

- ファンドスキームのデータ構造をExcel形式で出力
- シート構成: サマリー / 車両一覧 / 価格算出根拠 / キャッシュフロー / ステークホルダー

### Epic 4: 車両・在庫管理

#### 3.4.1 拡張機能

```python
class VehicleInventory(BaseModel):
    """ファンド組入車両の在庫管理"""
    vehicle_id: UUID
    fund_id: UUID
    sab_id: UUID                      # SABリンク
    acquisition_price: int
    current_nav: int                  # 現在帳簿価額
    residual_value_setting: int       # 残価設定額
    status: str                       # held / leased / disposing / disposed
    lease_contract_id: Optional[UUID]
    acquisition_date: date
    nav_history: list[dict]           # 月次NAV推移
```

#### 3.4.2 既存リース契約インポート

- CSV/Excelフォーマット定義
- バリデーション（必須項目、日付整合性、金額範囲）
- 一括登録 + エラーレポート

### Epic 5: 相場データ連携

#### 3.5.1 手動インポート機能

```python
class MarketDataImporter:
    """CSV/Excel相場データインポーター"""
    REQUIRED_COLUMNS = [
        'maker', 'model', 'year', 'mileage_km',
        'price_yen', 'auction_date', 'auction_site'
    ]

    def import_csv(self, file: UploadFile) -> ImportResult
    def import_excel(self, file: UploadFile) -> ImportResult
    def validate_row(self, row: dict) -> list[str]  # エラーメッセージ
```

#### 3.5.2 データフォーマット

| カラム | 型 | 必須 | 説明 |
|-------|---|-----|-----|
| maker | text | ○ | メーカー名 |
| model | text | ○ | 車種名 |
| year | int | ○ | 年式 |
| mileage_km | int | ○ | 走行距離 (km) |
| price_yen | int | ○ | 落札価格 (円) |
| auction_date | date | ○ | 落札日 |
| auction_site | text | - | オークションサイト名 |
| body_type | text | - | ボディタイプ |
| tonnage | float | - | 積載量 (t) |

### Epic 6: 請求管理・配信

#### 3.6.1 ワークフロー

```
請求書自動生成 (毎月1日) → 担当者確認 → 承認 → PDF生成 → メール送付
     ↓                      ↓           ↓        ↓          ↓
  [created]           [pending_review] [approved] [pdf_ready] [sent]
```

#### 3.6.2 データモデル

```sql
CREATE TABLE invoices (
    id UUID PRIMARY KEY,
    fund_id UUID REFERENCES funds(id),
    lease_contract_id UUID REFERENCES lease_contracts(id),
    invoice_number TEXT UNIQUE NOT NULL,
    billing_period_start DATE NOT NULL,
    billing_period_end DATE NOT NULL,
    subtotal BIGINT NOT NULL,
    tax_amount BIGINT NOT NULL,
    total_amount BIGINT NOT NULL,
    due_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'created'
        CHECK (status IN ('created','pending_review','approved','pdf_ready','sent','paid','overdue')),
    pdf_url TEXT,
    sent_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE invoice_approvals (
    id UUID PRIMARY KEY,
    invoice_id UUID REFERENCES invoices(id),
    approver_user_id UUID REFERENCES users(id),
    action TEXT NOT NULL CHECK (action IN ('approve','reject','request_change')),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE email_logs (
    id UUID PRIMARY KEY,
    invoice_id UUID REFERENCES invoices(id),
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','sent','failed','bounced')),
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Epic 7: ダッシュボード

#### 3.7.1 KPI一覧

| KPI | データソース | 更新頻度 |
|-----|------------|---------|
| 運用台数 | secured_asset_blocks (status='leased') | リアルタイム |
| 総投資額 | funds.total_fundraise_amount | リアルタイム |
| 利益転換ファンド数 | simulations + nav計算 | 日次 |
| 月次請求額 | invoices (当月) | 月次 |
| 入金率 | lease_payments (paid/total) | リアルタイム |
| 延滞件数 | lease_payments (status='overdue') | リアルタイム |
| 平均利回り | simulations.result.effective_yield_rate | リアルタイム |

---

## 4. データモデル・アーキテクチャ変更

### 4.1 新規テーブル

```sql
-- プライシングマスタ
CREATE TABLE pricing_masters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    parameters JSONB NOT NULL,  -- 利回り率、手数料率等
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- プライシングパラメータ履歴
CREATE TABLE pricing_parameter_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pricing_master_id UUID REFERENCES pricing_masters(id),
    parameter_key TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB NOT NULL,
    changed_by UUID REFERENCES users(id),
    changed_at TIMESTAMPTZ DEFAULT now()
);
```

### 4.2 既存テーブル変更

```sql
-- deal_stakeholders: role_type 拡張
ALTER TABLE deal_stakeholders
    DROP CONSTRAINT deal_stakeholders_role_type_check;
ALTER TABLE deal_stakeholders
    ADD CONSTRAINT deal_stakeholders_role_type_check
    CHECK (role_type IN (
        'spc', 'operator', 'investor', 'end_user',
        'guarantor', 'trustee',
        'private_placement_agent',  -- NEW
        'asset_manager',            -- NEW
        'accounting_firm',          -- NEW
        'accounting_delegate'       -- NEW
    ));

-- users: ステークホルダーロール追加
ALTER TABLE users ADD COLUMN stakeholder_role TEXT;
```

### 4.3 RBAC 権限マトリクス

| リソース | admin | operator | investor | end_user | AM | 私募取扱 | 会計 |
|---------|-------|----------|----------|----------|-----|---------|------|
| プライシングロジック | RW | R | - | - | R | - | - |
| 相場データ | RW | RW | - | - | R | - | - |
| シミュレーション結果 | RW | RW | R | R | R | - | - |
| 契約書(自社関連) | RW | RW | R | R | R | R | R |
| 請求書 | RW | RW | - | R | - | - | R |
| ファンド情報 | RW | R | R | - | R | - | R |
| 車両在庫 | RW | RW | R | - | R | - | - |
| ダッシュボード | RW | R | R(限定) | - | R | - | R(限定) |

---

## 5. 実装計画 — 30エージェント並列実行

### Phase 1: 基盤 (Agent 1-10)

| Agent | 担当 | 出力 |
|-------|------|------|
| 1 | DB Migration: pricing_masters, pricing_parameter_history | SQL |
| 2 | DB Migration: invoices, invoice_approvals, email_logs | SQL |
| 3 | DB Migration: deal_stakeholders拡張, users拡張, contract_templates追加シード | SQL |
| 4 | Pydantic Models: IntegratedPricing系 | Python |
| 5 | Pydantic Models: Invoice/Billing系 | Python |
| 6 | Pydantic Models: Stakeholder拡張, RBAC | Python |
| 7 | Core: AcquisitionPriceCalculator (Step 1) | Python |
| 8 | Core: ResidualValue拡張 + シナリオ分析 (Step 2) | Python |
| 9 | Core: LeasePriceCalculator (Step 3) | Python |
| 10 | Core: IntegratedPricingEngine オーケストレーター | Python |

### Phase 2: 機能 (Agent 11-20)

| Agent | 担当 | 出力 |
|-------|------|------|
| 11 | Core: NAVCalculator + 損益分岐 | Python |
| 12 | Core: ProposalGenerator (PDF) | Python |
| 13 | Repository: pricing_master_repo | Python |
| 14 | Repository: invoice_repo | Python |
| 15 | Repository: stakeholder_repo拡張 | Python |
| 16 | API: /api/v1/pricing (統合プライシング) | Python |
| 17 | API: /api/v1/invoices (請求管理) | Python |
| 18 | API: /api/v1/proposals (提案書PDF) | Python |
| 19 | API: /api/v1/contracts拡張 (9種類対応) | Python |
| 20 | API: /api/v1/market-data/import (CSV/Excelインポート) | Python |

### Phase 3: UI & テスト (Agent 21-30)

| Agent | 担当 | 出力 |
|-------|------|------|
| 21 | Template: 統合プライシングUI | HTML/Jinja2 |
| 22 | Template: 請求管理UI | HTML/Jinja2 |
| 23 | Template: ダッシュボード拡張 | HTML/Jinja2 |
| 24 | Template: 提案書プレビューUI | HTML/Jinja2 |
| 25 | Contract DOCX: 5種類追加テンプレート | Python/DOCX |
| 26 | RBAC Middleware + 権限チェック | Python |
| 27 | Email Service (請求書送付) | Python |
| 28 | Tests: プライシングエンジン | Python |
| 29 | Tests: API統合テスト | Python |
| 30 | Market Data Importer (CSV/Excel) | Python |

---

## 6. 非機能要件

| 項目 | 要件 |
|------|------|
| パフォーマンス | 価格算出 < 2秒、PDF生成 < 5秒 |
| セキュリティ | RBAC全エンドポイント適用、RLSポリシー更新 |
| 可用性 | 既存機能の稼働率 99.5% 維持 |
| データ整合性 | 価格算出パラメータの変更履歴（監査証跡） |
| 後方互換 | 既存API・UIの動作保証 |

---

## 7. リスクと軽減策

| リスク | 影響度 | 確率 | 軽減策 |
|-------|-------|------|-------|
| PricingEngine リファクタリングで既存機能破壊 | 高 | 中 | 既存クラスを維持、新エンジンは別エントリポイント |
| 契約書テンプレートの変数マッピング不足 | 中 | 高 | テンプレート変数の網羅的リスト作成 |
| PDF生成のVercel Lambda制約 (50MB/10秒) | 中 | 中 | 軽量ライブラリ選定、非同期生成 |
| RBAC適用漏れ | 高 | 低 | 権限チェックミドルウェア + E2Eテスト |

---

## 8. 承認

| 役割 | 氏名 | 日付 | 承認 |
|------|------|------|------|
| プロダクトマネージャー | | | ☐ |
| テックリード | | | ☐ |
| ファンドマネージャー | | | ☐ |
| マーケティング | | | ☐ |
