# 商用車リースバック価格最適化システム（CVLPOS）-- 現行システム仕様書

**バージョン:** 1.0（2026年4月7日時点の実装状態）
**本番URL:** https://auction-ten-iota.vercel.app

---

## 1. システム概要

### 1.1 システムの目的

商用車（トラック・トレーラー）のリースバック取引における買取価格の最適化を支援するWebアプリケーション。市場価格データのスクレイピング、残価計算、月額リース料算出、収益性判定を自動化し、営業担当者の査定業務を効率化する。

### 1.2 現在の状態

- 本番デプロイ済み（Vercel）
- ログイン認証、シミュレーション実行、市場データ閲覧、ダッシュボードが稼働中
- スクレイピングモジュールは実装済みだが、定期バッチの自動実行は未確認

### 1.3 技術スタック

| レイヤー | 技術 |
|---------|------|
| バックエンド | Python 3.x, FastAPI 0.1.0 |
| テンプレートエンジン | Jinja2 |
| フロントエンド | HTMX 1.9.12, Chart.js 4.x, カスタムCSS |
| データベース | PostgreSQL（Supabase hosted） |
| ORM/クライアント | supabase-py（REST API経由） |
| 認証 | Supabase Auth（email/password） |
| JWT | python-jose（ES256 / HS256） |
| ログ | structlog |
| 設定管理 | pydantic-settings（.envファイル） |
| スクレイピング | Playwright (headless Chromium) |
| デプロイ | Vercel（Python Lambda, @vercel/python） |
| 数値計算 | numpy |
| キャッシュ | cachetools (TTLCache) |

### 1.4 デプロイ構成

**vercel.json** による設定:
- エントリポイント: `api/index.py` （@vercel/python, maxLambdaSize: 50mb）
- 静的ファイル: `static/**` （@vercel/static）
- ルーティング: `/static/*` は静的配信、それ以外は全てPython Lambdaへ転送

### 1.5 アプリケーション設定（`app/config.py` Settings）

| 環境変数 | デフォルト | 説明 |
|---------|-----------|------|
| `APP_ENV` | `development` | 実行環境 |
| `APP_DEBUG` | `False` | デバッグモード |
| `APP_PORT` | `8000` | ポート番号 |
| `APP_SECRET_KEY` | `change-me` | アプリシークレット |
| `SUPABASE_URL` | `""` | Supabase URL |
| `SUPABASE_ANON_KEY` | `""` | Supabase匿名キー |
| `SUPABASE_SERVICE_ROLE_KEY` | `""` | Supabaseサービスロールキー |
| `DATABASE_URL` | `""` | DB接続文字列 |
| `SUPABASE_JWT_SECRET` | `""` | JWT検証シークレット |
| `SCRAPER_REQUEST_INTERVAL_SEC` | `3` | スクレイパーリクエスト間隔 |
| `SCRAPER_MAX_RETRIES` | `3` | スクレイパー最大リトライ |
| `SCRAPER_USER_AGENT` | `CommercialVehicleResearchBot/1.0` | UA文字列 |

---

## 2. 認証・認可

### 2.1 ログイン方式

- **認証基盤:** Supabase Auth（email/password方式）
- **JWT検証:** ES256（Supabase JWKS）およびHS256（フォールバック）
- **JWKSキャッシュ:** `cachetools.TTLCache`で1時間キャッシュ（`_jwks_cache`, maxsize=1, ttl=3600）
- **JWKSエンドポイント:** `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`

### 2.2 Cookie管理方式

認証トークンはHttpOnly Cookieで管理:

| Cookie名 | 属性 |
|----------|------|
| `access_token` | httponly=True, secure=True, samesite=lax, path=/ |
| `refresh_token` | httponly=True, secure=True, samesite=lax, path=/ |

- ログイン成功時: `_set_auth_cookies()` で両Cookieを設定
- ログアウト時: `_clear_auth_cookies()` で両Cookieを削除

### 2.3 ロール定義

`users` テーブルの `role` カラムで管理。CHECK制約:

| ロール | 権限 |
|--------|------|
| `admin` | 全機能へのフルアクセス、マスタデータCRUD、他ユーザーのシミュレーション閲覧 |
| `sales` | シミュレーション実行・閲覧（自分のもののみ）、市場データ閲覧 |
| `viewer` | 読み取り専用（DB定義上存在するが、コード内では未使用） |

### 2.4 認可チェック

- **`get_current_user()`** (`app/dependencies.py`): Cookieからaccess_tokenを取得し、JWT検証。`id`, `email`, `role` を返す。
- **`require_role(roles)`**: ロールベースアクセス制御のDependencyファクトリ。指定ロール以外は403を返す。
- **ページルート**: `_get_optional_user()` → `_require_auth()` パターンで認証チェック。未認証時は `/login` にリダイレクト（HTMX時は `HX-Redirect`ヘッダ）。

### 2.5 認証エンドポイント

| メソッド | パス | 機能 |
|---------|------|------|
| POST | `/auth/login` | メール/パスワード認証。成功時Cookieセット＋`/dashboard`リダイレクト |
| POST | `/auth/logout` | Cookie削除＋Supabaseセッション無効化（best-effort） |
| GET | `/auth/me` | 現在のユーザー情報（id, email, role）を返す |
| POST | `/auth/refresh` | refresh_tokenからaccess_tokenを再発行 |

---

## 3. 画面一覧と機能

### 3.1 ログイン画面

| 項目 | 値 |
|------|-----|
| URL | `GET /login` |
| テンプレート | `pages/login.html` |
| 認証 | 不要 |

**機能:**
- メールアドレス/パスワード入力フォーム
- HTMX経由で `POST /auth/login` にサブミット
- エラー表示領域 (`#login-error`) にHTMLフラグメントを差し替え
- 「ログイン状態を保持」チェックボックス（UIのみ、バックエンドロジックなし）
- 「パスワードを忘れた方」リンク（`/auth/forgot-password` -- 未実装）

### 3.2 ダッシュボード

| 項目 | 値 |
|------|-----|
| URL | `GET /dashboard` |
| テンプレート | `pages/dashboard.html` |
| 認証 | 必要 |

**表示データ（DBテーブル）:**
- `simulations`: シミュレーション件数（`id` count）、平均利回り（`expected_yield_rate` 平均）
- `vehicles`: アクティブ車両数（`is_active=True` count）

**KPIカード:**
1. シミュレーション数（全件）
2. 平均利回り（`expected_yield_rate` の平均 * 100 %表示）
3. 相場変動アラート（= アクティブ車両数）

**クイックアクション:**
- 「新規シミュレーション」ボタン → `/simulation/new`
- 「相場データ確認」ボタン → `/market-data`

**最近のシミュレーション:**
- `simulations` テーブルから `created_at DESC` で最新5件取得
- タイトル、車種/年式、買取価格、月額リース、利回り、ステータス、実行日を表示
- 60秒ごとにHTMX自動リフレッシュ（`hx-trigger="every 60s"`）

**ダッシュボードKPI API:**
- `GET /api/v1/dashboard/kpi` -- 今月の査定数（当月1日以降の `simulations` count）、平均利回り、市場データ数をHTMLフラグメントで返す

### 3.3 シミュレーション入力画面

| 項目 | 値 |
|------|-----|
| URL | `GET /simulation/new` |
| テンプレート | `pages/simulation.html` |
| 認証 | 必要 |

**表示データ（DBテーブル）:**
- `manufacturers`: メーカー一覧（ドロップダウン）
- `body_types`: ボディタイプ一覧（ドロップダウン）
- `vehicle_categories`: 車両クラス一覧（ドロップダウン）
- `vehicle_models`: 車種一覧（`is_active=True`, `display_order`順）
- `equipment_options`: 装備オプション一覧（`is_active=True`, `category,display_order`順）

**入力フォーム -- 車両情報:**

| フィールド | name属性 | タイプ | 必須 |
|-----------|---------|--------|------|
| メーカー | `maker` | select | Yes |
| 車種 | `model` / `model_select` / `model_custom` | select + text | Yes |
| 年式 | `registration_year_month` | select (2010-2026) | Yes |
| 走行距離 | `mileage_km` | number | Yes |
| クラス | `vehicle_class` | select | Yes |
| ボディタイプ | `body_type` | select | Yes |
| 取得価格 | `acquisition_price` | number | Yes |
| 簿価 | `book_value` | number | Yes |
| 装備オプション | `equipment` | checkbox (複数) | No |
| 架装オプション合計 | `body_option_value` | number (readonly) | No |

**入力フォーム -- リース条件:**

| フィールド | name属性 | デフォルト |
|-----------|---------|----------|
| 目標利回り (%) | `target_yield_rate` | 8 |
| リース期間 | `lease_term_months` | 24 (selected) |

**HTMX連携パターン:**
1. メーカー選択時: `hx-get="/api/v1/masters/models-by-maker"` で車種ドロップダウンを動的更新
2. フォームサブミット: `hx-post="/api/v1/simulations/calculate"` → `#result-area` にHTMLフラグメント差し替え

**車種選択ロジック:**
- ドロップダウンから選択 or 「その他（手動入力）」選択時にテキスト入力表示
- hidden input `model` に最終値を格納（`toggleCustomModel()` JavaScript関数）

**装備オプション合計の自動計算:**
- チェックボックス変更時にJavaScriptで `data-value` 属性の合計を算出
- `body_option_value` フィールドに自動反映

### 3.4 シミュレーション結果画面

| 項目 | 値 |
|------|-----|
| URL | `GET /simulation/{simulation_id}/result` |
| テンプレート | `pages/simulation_result.html` |
| 認証 | 必要 |

**表示データ:**
- `simulations` テーブルから `id` でレコード取得
- KPIカード: 買取価格、月額リース料、リース料総額、想定利回り
- 車両情報テーブル: 車種名、年式、走行距離、市場参考価格、リース期間
- 計算結果詳細（`result_summary_json` JSONBカラムから展開）

### 3.5 相場データ一覧画面

| 項目 | 値 |
|------|-----|
| URL | `GET /market-data` |
| テンプレート | `pages/market_data_list.html` |
| 認証 | 必要 |

**表示データ:**
- `vehicles` テーブル（`is_active=True`, `scraped_at DESC`, 初期20件）
- `manufacturers`: フィルタードロップダウン用
- `body_types`: フィルタードロップダウン用
- 統計: 全件数、平均価格、中央値価格

**フィルター（HTMX）:**

| フィルター | name属性 | 動作 |
|-----------|---------|------|
| メーカー | `maker` | `manufacturer_id` でフィルタ |
| ボディタイプ | `body_type` | `body_type` ilike でフィルタ |
| 年式（範囲） | `year_from`, `year_to` | `model_year` 範囲指定 |
| 価格帯（万円） | `price_from`, `price_to` | `price_yen` 範囲（万円→円変換: *10000） |
| キーワード | `keyword` | `model_name` or `maker` ilike |

- 各フィルター変更時に `hx-get="/market-data/table"` でテーブルフラグメントを差し替え
- キーワード入力は `keyup changed delay:400ms` でデバウンス

**テーブル行クリック:**
- `hx-get="/market-data/{id}"` で詳細画面に遷移（`hx-push-url="true"`）

### 3.6 相場データ詳細画面

| 項目 | 値 |
|------|-----|
| URL | `GET /market-data/{item_id}` |
| テンプレート | `pages/market_data_detail.html` |
| 認証 | 必要 |

**表示データ:**
- `vehicles` テーブルから `id` で単一レコード取得
- 類似車両: `vehicles` テーブルから `is_active=True`, 当該車両以外の5件

**表示項目:**
- 販売価格（税込/税別表示）
- 車両スペック: メーカー、車種、年式、走行距離、積載量、ボディタイプ、ミッション、燃料、所在地、掲載ステータス
- 類似車両テーブル
- 「この車種でシミュレーション」ボタン → `/simulation/new?maker=...&model=...`

### 3.7 共通レイアウト（base.html）

**サイドバーナビゲーション:**
- ダッシュボード (`/dashboard`)
- シミュレーション (`/simulation/new`)
- 相場データ (`/market-data`)
- ログアウト (`/auth/logout`)

**外部ライブラリ:**
- HTMX 1.9.12 (CDN: unpkg.com)
- Chart.js 4.x (CDN: cdn.jsdelivr.net)
- カスタムCSS: `/static/css/style.css`
- カスタムJS: `/static/js/app.js`

---

## 4. データベーススキーマ（現行）

### 4.1 users

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK, DEFAULT gen_random_uuid() |
| email | text | UNIQUE NOT NULL |
| full_name | text | NOT NULL |
| role | text | NOT NULL DEFAULT 'sales', CHECK ('admin','sales','viewer') |
| department | text | nullable |
| is_active | boolean | NOT NULL DEFAULT true |
| last_signed_in_at | timestamptz | nullable |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now(), トリガー自動更新 |

### 4.2 vehicle_categories

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| name | text | NOT NULL |
| code | text | UNIQUE NOT NULL |
| display_order | int | NOT NULL DEFAULT 0 |
| is_active | boolean | NOT NULL DEFAULT true |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**初期データ:**
- 大型トラック (LARGE, order=1)
- 中型トラック (MEDIUM, order=2)
- 小型トラック (SMALL, order=3)
- トレーラーヘッド (TRAILER_HEAD, order=4)
- トレーラーシャシー (TRAILER_CHASSIS, order=5)

### 4.3 manufacturers

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| name | text | NOT NULL |
| name_en | text | nullable |
| code | text | UNIQUE NOT NULL |
| country | text | NOT NULL DEFAULT 'JP' |
| display_order | int | NOT NULL DEFAULT 0 |
| is_active | boolean | NOT NULL DEFAULT true |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**初期データ:**
- いすゞ / Isuzu (ISZ)
- 日野 / Hino (HNO)
- 三菱ふそう / Mitsubishi Fuso (MFU)
- UDトラックス / UD Trucks (UDT)

### 4.4 body_types

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| name | text | NOT NULL |
| code | text | UNIQUE NOT NULL |
| category_id | uuid | FK → vehicle_categories(id), ON DELETE SET NULL |
| display_order | int | NOT NULL DEFAULT 0 |
| is_active | boolean | NOT NULL DEFAULT true |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**初期データ:**
ウイング(WING), バン(VAN), 平ボディ(FLAT), 冷凍冷蔵車(REFR), ダンプ(DUMP), クレーン付き(CRAN), タンクローリー(TANK), 塵芥車(TRSH), ミキサー(MIXR), キャリアカー(CARR)

### 4.5 vehicles

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| source_site | text | NOT NULL |
| source_url | text | nullable |
| source_id | text | nullable |
| category_id | uuid | NOT NULL, FK → vehicle_categories(id) |
| manufacturer_id | uuid | NOT NULL, FK → manufacturers(id) |
| body_type_id | uuid | FK → body_types(id) |
| model_name | text | NOT NULL |
| model_year | int | nullable |
| mileage_km | int | nullable |
| price_yen | bigint | nullable |
| price_tax_included | boolean | NOT NULL DEFAULT false |
| tonnage | numeric(6,2) | nullable |
| engine_displacement_cc | int | nullable |
| transmission | text | nullable |
| fuel_type | text | nullable |
| location_prefecture | text | nullable |
| image_url | text | nullable |
| scraped_at | timestamptz | NOT NULL DEFAULT now() |
| is_active | boolean | NOT NULL DEFAULT true |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**制約:** UNIQUE (source_site, source_id)

**インデックス:**
- idx_vehicles_category_id, idx_vehicles_manufacturer_id, idx_vehicles_body_type_id
- idx_vehicles_model_year, idx_vehicles_price_yen
- idx_vehicles_scraped_at (DESC)
- idx_vehicles_search_composite (category_id, manufacturer_id, body_type_id, model_year, price_yen) WHERE is_active=true

### 4.6 depreciation_curves

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| category_id | uuid | NOT NULL, FK → vehicle_categories(id) |
| manufacturer_id | uuid | FK → manufacturers(id) |
| body_type_id | uuid | FK → body_types(id) |
| curve_type | text | NOT NULL DEFAULT 'linear', CHECK ('linear','declining_balance','custom') |
| useful_life_years | int | NOT NULL |
| residual_rate | numeric(5,4) | NOT NULL DEFAULT 0.1000, CHECK (0-1) |
| custom_curve_json | jsonb | nullable |
| effective_from | date | NOT NULL DEFAULT CURRENT_DATE |
| effective_to | date | nullable |
| notes | text | nullable |
| created_by | uuid | FK → users(id) |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**初期データ:**
| カテゴリ | 償却方法 | 耐用年数 | 残価率 |
|---------|---------|---------|--------|
| LARGE | linear | 7 | 10% |
| MEDIUM | linear | 6 | 10% |
| SMALL | linear | 5 | 10% |
| TRAILER_HEAD | declining_balance | 8 | 8% |
| TRAILER_CHASSIS | linear | 10 | 5% |

### 4.7 simulations

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| user_id | uuid | NOT NULL, FK → users(id) |
| title | text | nullable |
| category_id | uuid | FK → vehicle_categories(id) |
| manufacturer_id | uuid | FK → manufacturers(id) |
| body_type_id | uuid | FK → body_types(id) |
| target_model_name | text | nullable |
| target_model_year | int | nullable |
| target_mileage_km | int | nullable |
| market_price_yen | bigint | nullable |
| purchase_price_yen | bigint | nullable |
| lease_monthly_yen | bigint | nullable |
| lease_term_months | int | nullable |
| total_lease_revenue_yen | bigint | nullable |
| expected_yield_rate | numeric(6,4) | nullable |
| result_summary_json | jsonb | nullable |
| status | text | NOT NULL DEFAULT 'draft', CHECK ('draft','completed','submitted','approved') |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**注意:** API層では `input_data` (jsonb) と `result` (jsonb) カラムを使用しているが、マイグレーションSQLには含まれていない。SimulationRepositoryが実装するスキーマとマイグレーションに差異がある可能性がある。

### 4.8 simulation_params

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| simulation_id | uuid | NOT NULL, FK → simulations(id) ON DELETE CASCADE |
| param_key | text | NOT NULL |
| param_value | numeric(18,6) | nullable |
| param_unit | text | nullable |
| description | text | nullable |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

**制約:** UNIQUE (simulation_id, param_key)

### 4.9 scraping_logs

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| source_site | text | NOT NULL |
| status | text | NOT NULL DEFAULT 'running', CHECK ('running','completed','failed','cancelled') |
| started_at | timestamptz | NOT NULL DEFAULT now() |
| finished_at | timestamptz | nullable |
| total_pages | int | nullable |
| processed_pages | int | NOT NULL DEFAULT 0 |
| new_records | int | NOT NULL DEFAULT 0 |
| updated_records | int | NOT NULL DEFAULT 0 |
| skipped_records | int | NOT NULL DEFAULT 0 |
| error_count | int | NOT NULL DEFAULT 0 |
| error_details | jsonb | nullable |
| triggered_by | text | NOT NULL DEFAULT 'cron' |
| created_at | timestamptz | NOT NULL DEFAULT now() |
| updated_at | timestamptz | NOT NULL DEFAULT now() |

### 4.10 vehicle_price_history

| カラム | 型 | 制約 |
|--------|-----|------|
| id | bigserial | PK |
| source_site | varchar(50) | NOT NULL |
| source_vehicle_id | varchar(100) | NOT NULL |
| price_yen | int | NOT NULL |
| price_tax_included | boolean | nullable |
| observed_at | timestamptz | NOT NULL DEFAULT now() |

### 4.11 funds（ファンド管理）

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| fund_name | text | NOT NULL |
| fund_code | text | NOT NULL UNIQUE |
| manager_user_id | uuid | FK → users(id) |
| establishment_date | date | NOT NULL |
| operation_start_date | date | nullable |
| operation_end_date | date | nullable |
| target_yield_rate | numeric(6,4) | CHECK >= 0 |
| operation_term_months | integer | CHECK > 0 |
| total_fundraise_amount | bigint | CHECK >= 0 |
| current_cash_balance | bigint | NOT NULL DEFAULT 0 |
| reserve_amount | bigint | NOT NULL DEFAULT 0, CHECK >= 0 |
| status | text | NOT NULL DEFAULT 'preparing', CHECK ('preparing','fundraising','active','liquidating','closed') |
| description | text | nullable |
| created_at / updated_at | timestamptz | |

### 4.12 fund_investors

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| fund_id | uuid | NOT NULL, FK → funds(id) |
| investor_name | text | NOT NULL |
| investor_type | text | NOT NULL, CHECK ('institutional','individual') |
| investor_contact_email | text | nullable |
| investment_amount | bigint | NOT NULL, CHECK > 0 |
| investment_ratio | numeric(8,6) | CHECK 0-1 |
| investment_date | date | nullable |
| cumulative_distribution | bigint | NOT NULL DEFAULT 0, CHECK >= 0 |
| is_active | boolean | NOT NULL DEFAULT true |

**制約:** UNIQUE (fund_id, investor_name)

### 4.13 lease_contracts

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| fund_id | uuid | NOT NULL, FK → funds(id) |
| contract_number | text | NOT NULL UNIQUE |
| lessee_company_name | text | NOT NULL |
| lessee_corporate_number | text | nullable |
| lessee_contact_person | text | nullable |
| lessee_contact_email | text | nullable |
| lessee_contact_phone | text | nullable |
| contract_start_date | date | NOT NULL |
| contract_end_date | date | NOT NULL |
| lease_term_months | integer | NOT NULL, CHECK > 0 |
| monthly_lease_amount | bigint | NOT NULL, CHECK > 0 |
| monthly_lease_amount_tax_incl | bigint | NOT NULL, CHECK > 0 |
| tax_rate | numeric(5,4) | NOT NULL DEFAULT 0.1000, CHECK >= 0 |
| residual_value | bigint | DEFAULT 0, CHECK >= 0 |
| payment_day | integer | NOT NULL DEFAULT 25, CHECK 1-31 |
| status | text | NOT NULL DEFAULT 'draft', CHECK ('draft','active','overdue','terminated','completed') |
| termination_date | date | nullable |
| termination_reason | text | nullable |

### 4.14 lease_payments

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| lease_contract_id | uuid | NOT NULL, FK → lease_contracts(id) ON DELETE CASCADE |
| payment_sequence | integer | NOT NULL, CHECK > 0 |
| scheduled_date | date | NOT NULL |
| scheduled_amount | bigint | NOT NULL, CHECK > 0 |
| scheduled_amount_tax_incl | bigint | NOT NULL, CHECK > 0 |
| status | text | NOT NULL DEFAULT 'scheduled', CHECK ('scheduled','paid','partial','overdue','waived') |
| actual_payment_date | date | nullable |
| actual_amount | bigint | CHECK >= 0 |
| overdue_days | integer | NOT NULL DEFAULT 0, CHECK >= 0 |

**制約:** UNIQUE (lease_contract_id, payment_sequence)

### 4.15 secured_asset_blocks (SAB)

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| fund_id | uuid | NOT NULL, FK → funds(id) |
| lease_contract_id | uuid | FK → lease_contracts(id) |
| vehicle_id | uuid | FK → vehicles(id) |
| sab_number | text | NOT NULL UNIQUE |
| vehicle_description | text | nullable |
| acquisition_price | bigint | NOT NULL, CHECK > 0 |
| acquisition_date | date | NOT NULL |
| b2b_wholesale_valuation | bigint | CHECK >= 0 |
| option_adjustment | bigint | NOT NULL DEFAULT 0 |
| adjusted_valuation | bigint | CHECK >= 0 |
| ltv_ratio | numeric(6,4) | CHECK >= 0 |
| valuation_date | date | nullable |
| status | text | NOT NULL DEFAULT 'held', CHECK ('held','leased','disposing','disposed') |
| disposal_price | bigint | CHECK >= 0 |
| disposal_date | date | nullable |

### 4.16 fee_records

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| fund_id | uuid | NOT NULL, FK → funds(id) |
| lease_contract_id | uuid | FK → lease_contracts(id) |
| sab_id | uuid | FK → secured_asset_blocks(id) |
| fee_type | text | NOT NULL, CHECK ('brokerage_fee','management_fee','early_termination_fee','disposal_fee') |
| base_amount | bigint | NOT NULL, CHECK > 0 |
| fee_rate | numeric(8,6) | NOT NULL, CHECK >= 0 |
| fee_amount | bigint | NOT NULL, CHECK > 0 |
| calculation_date | date | NOT NULL |
| payment_status | text | NOT NULL DEFAULT 'calculated', CHECK ('calculated','invoiced','paid') |

### 4.17 fund_distributions

| カラム | 型 | 制約 |
|--------|-----|------|
| id | uuid | PK |
| fund_id | uuid | NOT NULL, FK → funds(id) |
| investor_id | uuid | NOT NULL, FK → fund_investors(id) |
| distribution_date | date | NOT NULL |
| distribution_type | text | NOT NULL DEFAULT 'monthly', CHECK ('monthly','interim','final') |
| distribution_amount | bigint | NOT NULL, CHECK > 0 |
| annualized_yield | numeric(6,4) | nullable |

### 4.18 RLSポリシー

全テーブルでRow Level Securityが有効化されている。

| テーブル | SELECT | INSERT | UPDATE | DELETE |
|---------|--------|--------|--------|--------|
| users | 自分 or admin | admin のみ | 自分 or admin | admin のみ |
| vehicle_categories | 全ユーザー | admin | admin | admin |
| manufacturers | 全ユーザー | admin | admin | admin |
| body_types | 全ユーザー | admin | admin | admin |
| vehicles | 全ユーザー | service_role | service_role | service_role |
| depreciation_curves | 全ユーザー | admin | admin | admin |
| simulations | 自分 or admin | 自分のみ | 自分のみ | 自分のみ |
| simulation_params | 親simulation経由 | 親simulation経由 | 親simulation経由 | 親simulation経由 |
| scraping_logs | admin | service_role | service_role | -- |
| vehicle_price_history | admin | service_role | -- | -- |

**注意:** ファンド管理テーブル（funds, fund_investors, lease_contracts, lease_payments, secured_asset_blocks, fee_records, fund_distributions）にはRLSポリシーが未定義。

---

## 5. 計算ロジック（現行実装）

本システムには2つの計算パスが存在する:
1. **PricingEngine クラス** -- 市場データを活用した本格的な計算（`POST /api/v1/simulations`、認証必要、結果DB保存）
2. **簡易関数群** (`_max_purchase_price`, `_residual_value`, `_monthly_lease_fee`, `_assessment`) -- Quick Calculation（`POST /api/v1/simulations/calculate`、認証不要、結果非保存）

### 5.1 買取上限価格

#### PricingEngine方式

```
max_price = base_market_price * condition_factor * trend_factor * (1 - safety_margin_rate)
```

- `base_market_price`: オークション/小売価格の加重中央値
- `condition_factor`: 現在は固定 1.0
- `trend_factor`: 直近価格中央値 / 基準価格中央値（0.80 - 1.20にクランプ）
- `safety_margin_rate`: 動的安全マージン（後述）

**base_market_price計算:**

```python
if deviation > acceptable_deviation_threshold (0.15):
    weight = elevated_auction_weight (0.85)
else:
    weight = auction_weight (0.70)
base = weight * auction_median + (1 - weight) * retail_median
```

**safety_margin計算:**

```python
cv = std(prices) / mean(prices)   # 変動係数
dynamic = base_safety_margin (0.05) + cv * volatility_premium (1.5)
margin = clamp(dynamic, min_safety (0.03), max_safety (0.20))
```

サンプルが2未満の場合はカテゴリ別デフォルト:
- SMALL: 0.05, MEDIUM: 0.05, LARGE: 0.07, TRAILER_HEAD: 0.08, TRAILER_CHASSIS: 0.06

#### 簡易関数方式（`_max_purchase_price`）

```python
def _max_purchase_price(book_value, market_median, body_option_value=0):
    anchor = max(book_value, market_median)
    return int(anchor * 1.10) + body_option_value
```

Quick Calculationでは `recommended_price = int(max_price * 0.95)` （上限の95%）。

### 5.2 残価計算

#### PricingEngine方式

**定額法 (straight_line):**

```python
salvage_value = purchase_price * salvage_ratio
monthly_dep = (purchase_price - salvage_value) / (useful_life_years * 12)
chassis_value = max(purchase_price - monthly_dep * elapsed_months, salvage_value)
```

**定率法 (declining_balance):**

```python
rate = 2.0 / useful_life_years
chassis_value = max(purchase_price * (1 - rate)^elapsed_years, salvage_value)
```

**最終残価:**

```python
residual = chassis_value * body_depreciation_factor * mileage_adjustment
```

**カテゴリ別パラメータ:**

| カテゴリ | 耐用年数 | 残存率 | 年間標準走行距離 |
|---------|---------|--------|---------------|
| SMALL | 7年 | 10% | 30,000km |
| MEDIUM | 9年 | 8% | 50,000km |
| LARGE | 10年 | 7% | 80,000km |
| TRAILER_HEAD | 10年 | 6% | 100,000km |
| TRAILER_CHASSIS | 12年 | 5% | -- |

**ボディタイプ別減価率テーブル（`BODY_DEPRECIATION_TABLES`）:**

各ボディタイプに対し (経過年数, 係数) のタプルリストで定義。線形補間で中間値を計算。

例: WING型の場合
- 0年: 1.00, 1年: 0.92, 2年: 0.85, 3年: 0.78, ..., 15年: 0.22

対応ボディタイプ: FLAT, VAN, WING, REFR, DUMP, CRAN, TAIL_LIFT, MIXER, TANK, GARBAGE

**走行距離調整係数:**

```python
expected_mileage = annual_standard * elapsed_years
mileage_ratio = actual_mileage / expected_mileage
deviation = mileage_ratio - 1.0

if deviation > 0:  # 過走行
    factor = 1.0 - deviation * over_mileage_penalty_rate (0.30)
else:  # 低走行
    factor = 1.0 - deviation * under_mileage_bonus_rate (0.15)

factor = clamp(factor, mileage_adj_floor (0.70), mileage_adj_ceiling (1.10))
```

#### 簡易関数方式（`_residual_value`）

デフォルト残価率テーブル:

| リース期間 | 残価率 |
|-----------|--------|
| 12ヶ月以下 | 50% |
| 24ヶ月以下 | 30% |
| 36ヶ月以下 | 20% |
| 48ヶ月以下 | 15% |
| 60ヶ月以下 | 10% |
| 60ヶ月超 | 5% |

```python
def _residual_value(purchase_price, lease_term_months, residual_rate=None):
    # residual_rateがNoneの場合、上記テーブルから自動決定
    return (int(purchase_price * residual_rate), residual_rate)
```

### 5.3 月額リース料

#### PricingEngine方式

```python
# 元本回収（定額法）
principal_recovery = (purchase_price - residual_value) / lease_term_months

# 利息（平均残高方式）
annual_rate = fund_cost_rate (0.020) + credit_spread (0.015) + liquidity_premium (0.005)  # = 0.040
average_balance = (purchase_price + residual_value) / 2
interest_charge = average_balance * annual_rate / 12

# 管理費
management_fee = purchase_price * monthly_management_fee_rate (0.002) + fixed_monthly_admin_cost (5000)

# 利益マージン
profit_margin = (principal_recovery + interest_charge + management_fee) * profit_margin_rate (0.08)

# 合計
total = principal_recovery + interest_charge + management_fee + profit_margin
```

#### PMT方式（`calculate_from_target_yield`）

```python
r = target_yield / 12
PV_residual = residual_value / (1 + r)^n
net = purchase_price - PV_residual
PMT = net * r / (1 - (1 + r)^(-n))
```

#### 簡易関数方式（`_monthly_lease_fee`）

```python
depreciable = purchase_price - residual_value
mr = target_yield_rate / 12

# PMT計算
factor = (mr * (1 + mr)^n) / ((1 + mr)^n - 1)
base = int(depreciable * factor)

# 残価に対する金利
residual_cost = int(residual_value * mr)

total = base + residual_cost + insurance_monthly + maintenance_monthly
```

Quick Calculationでは `insurance_monthly=15000`, `maintenance_monthly=10000` を固定使用。

### 5.4 判定ロジック

#### PricingEngine方式（`determine_assessment`）

```
推奨: effective_yield >= 5% AND breakeven_ratio <= 70%
非推奨: effective_yield < 2% OR breakeven is None OR breakeven_ratio > 90%
要検討: その他
```

（`breakeven_ratio = breakeven_months / lease_term`）

#### 簡易関数方式（`_assessment`）

```python
def _assessment(effective_yield, target_yield, market_deviation):
    if effective_yield >= target_yield and abs(market_deviation) <= 0.05:
        return "推奨"
    if effective_yield < target_yield * 0.5 or abs(market_deviation) > 0.10:
        return "非推奨"
    return "要検討"
```

Quick Calculationでは `market_deviation=0.05` 固定で呼び出し。

### 5.5 月次スケジュール生成

#### Quick Calculation方式（`/calculate`エンドポイント内）

```python
dep_per_month = (recommended_price - residual) / lease_term_months
mr = (target_yield_rate / 100) / 12

for month in range(1, lease_term_months + 1):
    asset_value = max(int(recommended_price - dep_per_month * month), residual)
    cumulative_income += monthly_fee
    prev_asset = recommended_price - dep_per_month * (month - 1)
    dep_expense = int(prev_asset - asset_value)
    fin_cost = int(prev_asset * mr)
    net_income = monthly_fee - 15000 - 10000  # 保険・メンテナンス控除
    profit = net_income - dep_expense - fin_cost
    cumulative_profit += profit
    net_fund_value = asset_value + cumulative_income
    nav_ratio = net_fund_value / recommended_price
```

#### PricingEngine方式（`calculate_monthly_schedule`）

```python
dep_expense = (purchase_price - salvage_value) / (useful_life_years * 12)
asset_value = max(purchase_price - dep_expense * m, salvage_value)
financing_cost = remaining_balance * monthly_rate  # monthly_rate = annual_rate / 12
monthly_profit = lease_income - dep_expense - financing_cost

# 途中解約損失推定
forced_sale_value = asset_value * forced_sale_discount (0.85)
remaining_payments = min(penalty_months (3), lease_term - m) * monthly_payment
termination_loss = forced_sale_value + cumulative_income - purchase_price - remaining_payments
```

### 5.6 損益分岐点

```python
# 月mで breakeven:
cumulative_income(m) >= purchase_price - asset_value(m)
```

Quick Calculationでは:
```python
net_monthly = monthly_fee - 15000 - 10000
breakeven = math.ceil(recommended_price / net_monthly)
```

### 5.7 実効利回り

```python
total_income = monthly_lease_fee * lease_term
total_cost = recommended_price - residual_value
effective_yield = ((total_income - total_cost) / recommended_price) * (12 / lease_term)
```

### 5.8 バリュートランスファー分析

Quick Calculationで算出。NAV (Net Asset Value) 計算:

```python
net_fund_value = asset_value + cumulative_income
nav_ratio = net_fund_value / recommended_price
```

---

## 6. APIエンドポイント一覧（現行）

### 6.1 認証 API (`/auth`)

| メソッド | パス | 概要 | 認証 |
|---------|------|------|------|
| POST | `/auth/login` | email/password認証 | 不要 |
| POST | `/auth/logout` | ログアウト | 不要 |
| GET | `/auth/me` | 現在のユーザー情報取得 | 必要 |
| POST | `/auth/refresh` | アクセストークン再発行 | Cookie(refresh_token) |

### 6.2 ページルート

| メソッド | パス | 概要 | 認証 |
|---------|------|------|------|
| GET | `/` | `/dashboard` にリダイレクト | -- |
| GET | `/login` | ログインページ | 不要 |
| GET | `/dashboard` | ダッシュボード | 必要 |
| GET | `/simulation/new` | シミュレーション入力 | 必要 |
| GET | `/simulation/{id}/result` | シミュレーション結果 | 必要 |
| GET | `/market-data` | 相場データ一覧 | 必要 |
| GET | `/market-data/table` | テーブルフラグメント（HTMX） | 不要 |
| GET | `/market-data/{id}` | 相場データ詳細 | 必要 |

### 6.3 ダッシュボード API (`/api/v1/dashboard`)

| メソッド | パス | 概要 | レスポンス |
|---------|------|------|----------|
| GET | `/api/v1/dashboard/kpi` | KPI HTMLフラグメント | HTML |

### 6.4 シミュレーション API (`/api/v1/simulations`)

| メソッド | パス | 概要 | 認証 | レスポンス |
|---------|------|------|------|----------|
| POST | `/api/v1/simulations` | シミュレーション実行・保存 | 必要 | JSON/HTML |
| GET | `/api/v1/simulations` | シミュレーション履歴一覧 | 必要 | JSON/HTML |
| GET | `/api/v1/simulations/{id}` | シミュレーション詳細 | 必要 | JSON/HTML |
| DELETE | `/api/v1/simulations/{id}` | シミュレーション削除（draftのみ） | 必要 | JSON |
| POST | `/api/v1/simulations/compare` | 2件のシミュレーション比較 | 必要 | JSON |
| POST | `/api/v1/simulations/calculate` | Quick計算（保存なし） | 不要 | HTML |

**`POST /api/v1/simulations` リクエストボディ (SimulationInput):**

```json
{
  "maker": "いすゞ",
  "model": "エルフ",
  "model_code": "TRG-NMR85AN",
  "registration_year_month": "2020-04",
  "mileage_km": 85000,
  "acquisition_price": 6000000,
  "book_value": 3200000,
  "vehicle_class": "小型",
  "payload_ton": 2.0,
  "body_type": "平ボディ",
  "body_option_value": 500000,
  "target_yield_rate": 0.08,
  "lease_term_months": 36,
  "residual_rate": 0.10,
  "insurance_monthly": 15000,
  "maintenance_monthly": 10000,
  "remarks": "特記事項なし"
}
```

**SimulationResult レスポンス:**

```json
{
  "max_purchase_price": 3800000,
  "recommended_purchase_price": 3500000,
  "estimated_residual_value": 350000,
  "residual_rate_result": 0.10,
  "monthly_lease_fee": 120000,
  "total_lease_fee": 4320000,
  "breakeven_months": 24,
  "effective_yield_rate": 0.082,
  "market_median_price": 3600000,
  "market_sample_count": 15,
  "market_deviation_rate": -0.028,
  "assessment": "推奨",
  "monthly_schedule": [
    {
      "month": 1,
      "asset_value": 3100000,
      "lease_income": 120000,
      "cumulative_income": 120000,
      "depreciation_expense": 80000,
      "financing_cost": 20000,
      "monthly_profit": 20000,
      "cumulative_profit": 20000,
      "termination_loss": -500000
    }
  ]
}
```

**`POST /api/v1/simulations/compare` リクエスト:**

```json
{
  "simulation_ids": ["uuid1", "uuid2"]
}
```

**ComparisonDiff レスポンスに含まれるフィールド:**
max_purchase_price, recommended_purchase_price, monthly_lease_fee, total_lease_fee, effective_yield_rate, breakeven_months, estimated_residual_value, market_deviation_rate

### 6.5 市場価格 API (`/api/v1/market-prices`)

| メソッド | パス | 概要 | 認証 |
|---------|------|------|------|
| GET | `/api/v1/market-prices/` | 車両一覧（検索・ページネーション） | 必要 |
| GET | `/api/v1/market-prices/statistics` | 統計情報 | 必要 |
| GET | `/api/v1/market-prices/export` | CSVエクスポート | 必要 |
| POST | `/api/v1/market-prices/import` | CSVインポート | admin/service_role |
| GET | `/api/v1/market-prices/{id}` | 車両詳細 | 必要 |
| POST | `/api/v1/market-prices/` | 車両登録 | admin/service_role |
| PUT | `/api/v1/market-prices/{id}` | 車両更新 | admin/service_role |
| DELETE | `/api/v1/market-prices/{id}` | 車両論理削除 | admin/service_role |

**CSVエクスポートカラム:** id, source_site, source_url, source_id, maker, model_name, body_type, model_year, mileage_km, price_yen, price_tax_included, tonnage, transmission, fuel_type, location_prefecture, listing_status, scraped_at, created_at, updated_at

**CSVインポート必須フィールド:** source_site, source_url, source_id, maker, model_name, body_type, model_year, mileage_km, price_tax_included, listing_status, scraped_at

**統計レスポンスフィールド:** count, avg, median, min, max, std

### 6.6 マスタデータ API (`/api/v1/masters`)

| メソッド | パス | 概要 | 認証 |
|---------|------|------|------|
| GET | `/api/v1/masters/makers` | メーカー一覧 | 必要 |
| POST | `/api/v1/masters/makers` | メーカー作成 | admin |
| GET | `/api/v1/masters/makers/{id}/models` | 車種一覧（メーカー別） | 必要 |
| POST | `/api/v1/masters/makers/{id}/models` | 車種作成 | admin |
| GET | `/api/v1/masters/body-types` | ボディタイプ一覧 | 必要 |
| POST | `/api/v1/masters/body-types` | ボディタイプ作成 | admin |
| PUT | `/api/v1/masters/body-types/{id}` | ボディタイプ更新 | admin |
| DELETE | `/api/v1/masters/body-types/{id}` | ボディタイプ論理削除 | admin |
| GET | `/api/v1/masters/categories` | 車両カテゴリ一覧 | 必要 |
| GET | `/api/v1/masters/depreciation-curves` | 償却カーブ一覧 | 必要 |
| POST | `/api/v1/masters/depreciation-curves` | 償却カーブ作成/更新 | admin |
| GET | `/api/v1/masters/models-by-maker` | メーカー名から車種select options | 不要 |

**HTMX連携:** GET系エンドポイントは `HX-Request` ヘッダ検知時に `<option>` HTML要素を直接返却。

### 6.7 ヘルスチェック

| メソッド | パス | 概要 |
|---------|------|------|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/favicon.ico` | favicon.svgを返却 |

---

## 7. ビジュアライゼーション（現行）

Quick Calculation (`POST /api/v1/simulations/calculate`) のレスポンスHTMLに3つのChart.jsチャートが含まれる。

### 7.1 バリュートランスファー分析チャート

- **チャートID:** `chart-value-transfer`
- **タイプ:** line
- **データセット:**
  - 資産簿価（紫 `#6366f1`, fill, tension 0.3）
  - 累積リース収入（緑 `#10b981`, fill, tension 0.3）
- **Y軸:** 円単位、フォーマッタで「万」表示
- **ラベル:** 「1月」「2月」... の月次ラベル

### 7.2 NAV（純資産価値）推移チャート

- **チャートID:** `chart-nav`
- **タイプ:** line
- **データセット:**
  - NAV比率 % (青 `#2563eb`, fill, tension 0.3)
  - 60%ライン -- 安全基準（黄 `#f59e0b`, borderDash [8,4], pointRadius 0）
- **Y軸:** min 0, max 200, %表示
- **意味:** `NAV比率 = (資産簿価 + 累計リース収入) / 推奨買取価格 * 100`

### 7.3 月次損益チャート

- **チャートID:** `chart-pnl`
- **タイプ:** bar + line（複合）
- **データセット:**
  - 月次損益（棒: 正=緑 `rgba(16,185,129,0.7)`, 負=赤 `rgba(239,68,68,0.7)`, borderRadius 3）
  - 累積損益（線: 青 `#2563eb`, y1軸）
- **Y軸:** y（月次損益、万円表示）、y1（累積損益、万円表示）

### 7.4 月次スケジュールテーブル

折りたたみ可能なテーブル（デフォルト非表示）:

| 月 | 資産簿価 | リース収入 | 累積収入 | 減価償却費 | 金融費用 | 月次損益 | 累積損益 | NAV比率 |
|----|---------|----------|---------|----------|---------|---------|---------|---------|

---

## 8. スクレイピング機能（現行）

### 8.1 アーキテクチャ

```
BaseScraper (ABC)
  +-- TruckKingdomScraper  (truck-kingdom.com)
  +-- SteerlinkScraper     (steerlink.co.jp)

ScraperScheduler (orchestrator)
  +-- VehicleParser (normalizer)
```

- **ブラウザ:** Playwright (headless Chromium)
- **レートリミット:** ランダム遅延 3-7秒（`_rate_limit()`）
- **リトライ:** 最大3回、指数バックオフ（`_retry()`）

### 8.2 対象サイト

#### トラック王国 (truck-kingdom.com)

- **クラス:** `TruckKingdomScraper`
- **site_name:** `truck_kingdom`
- **BASE_URL:** `https://www.truck-kingdom.com`
- **カテゴリ:** large-truck, medium-truck, small-truck, trailer
- **一覧URL形式:** `{BASE_URL}/list/{category}/?page={n}`
- **最大ページ数:** 設定可能（デフォルト20）

#### ステアリンク (steerlink.co.jp)

- **クラス:** `SteerlinkScraper`
- **site_name:** `steerlink`
- **BASE_URL:** `https://www.steerlink.co.jp`
- **カテゴリ:** large, medium, small, trailer, tractor, bus
- **一覧URL形式:** `{BASE_URL}/stock/list/{category}/?page={n}`

### 8.3 取得項目

一覧ページから取得: title, url, price, year, mileage, image_url, maker, body_type, location, source_id

詳細ページから追加取得: model_name, model_code, tonnage_text, displacement, transmission, fuel_type, inspection, body_maker

### 8.4 正規化ルール（`scraper/utils.py`）

**全角→半角変換:** `zenkaku_to_hankaku()` で全角ASCII文字を半角に統一

**メーカー名正規化 (`MAKER_MAP`):**
- ISUZU / いすず / イスズ → いすゞ
- HINO / ヒノ → 日野
- FUSO / 三菱 / ミツビシ → 三菱ふそう
- UD / 日産ディーゼル → UDトラックス
- 他、トヨタ、日産、マツダ等にも対応

**車種名正規化 (`MODEL_MAP`):**
- GIGA → ギガ, FORWARD → フォワード, ELF → エルフ
- PROFIA → プロフィア, RANGER → レンジャー, DUTRO → デュトロ
- 他主要モデル名に対応

**ボディタイプ正規化 (`BODY_TYPE_MAP`):**
- ウィング/ウイングボディ → ウイング
- 冷蔵冷凍車/冷凍車/冷蔵車 → 冷凍車
- パッカー車/パッカー/ゴミ収集車 → 塵芥車
- 他約40パターンに対応

**価格正規化 (`normalize_price`):**
- 「450万円(税込)」→ (4500000, True)
- 「12,500,000円」→ (12500000, False)
- 「ASK」/「応談」→ (None, False)

**走行距離正規化 (`normalize_mileage`):**
- 「18.5万km」→ 185000
- 「185,000km」→ 185000

**年式正規化 (`normalize_year`):**
- 和暦対応: R1→2019, H30→2018, S63→1988
- 「令和3年」→ 2021, 「平成30年」→ 2018
- 西暦直接: 「2019年」→ 2019

**バリデーション (`is_valid_vehicle`):**
- 必須: maker, model, year, price
- 年式範囲: 1980-2030
- 価格範囲: 10,000 - 500,000,000円
- 走行距離範囲: 0 - 5,000,000km

### 8.5 データベース連携（`ScraperScheduler`）

1. `scraping_logs` テーブルにステータス `running` でログ作成
2. サイトスクレイパー実行（full or listing モード）
3. `VehicleParser.parse_batch()` で正規化
4. `vehicles` テーブルにUPSERT（`source_site`, `source_id` で一意性判定）
5. 価格変更時は `vehicle_price_history` に履歴記録
6. `manufacturer_id`, `body_type_id`, `category_id` は名前からルックアップして解決
7. ログ更新（completed / failed）

### 8.6 バッチスケジュール

現在のコードにはcronジョブの自動スケジュール設定は含まれていない。`scraping_logs.triggered_by` フィールドのデフォルトは `'cron'` だが、`ScraperScheduler` は手動実行を想定した設計（`triggered_by` は config で `'manual'` にデフォルト設定）。

---

## 9. 装備オプション機能

### 9.1 equipment_options テーブル

コード内で `equipment_options` テーブルが参照されている（`app/api/pages.py` の `simulation_new_page`）。ただし、このテーブルのCREATEマイグレーションSQLは確認されたマイグレーションファイルには含まれていない。

**参照箇所:**
```python
options_resp = client.table("equipment_options").select("*").eq("is_active", True).order("category,display_order").execute()
```

**想定カラム（テンプレートでの使用から推定）:**
- `id`: UUID
- `name`: テキスト（装備名）
- `category`: テキスト（分類コード）
- `estimated_value_yen`: 整数（推定価値円）
- `display_order`: 整数
- `is_active`: boolean

### 9.2 カテゴリ定義（テンプレート内）

| カテゴリコード | 表示名 |
|-------------|--------|
| `loading` | 荷役関連 |
| `crane` | クレーン関連 |
| `refrigeration` | 冷凍冷蔵関連 |
| `safety` | 安全装置 |
| `comfort` | 快適装備 |
| `other` | その他 |

### 9.3 チェックボックス選択→合計計算の仕組み

1. テンプレートで各オプションを `<input type="checkbox" name="equipment" value="{name}" data-value="{estimated_value_yen}">` として出力
2. JavaScriptの `change` イベントリスナーで `equipment` チェックボックスの変更を検知
3. チェック済みのチェックボックスの `data-value` 属性を合算
4. `body_option_value` フィールド（readonly）に合計値をセット

### 9.4 リース価格への影響

- Quick Calculationでは `body_option_value` が `_max_purchase_price()` の引数として渡される
- `_max_purchase_price(book_value, acquisition_price, body_option_value)` → `anchor = max(book_value, acquisition_price)` → `int(anchor * 1.10) + body_option_value`
- つまり、装備オプション合計額が買取上限価格に加算される

### 9.5 vehicle_models テーブル

`equipment_options` と同様、`vehicle_models` テーブルもコード内で参照されているがマイグレーションSQLに含まれていない。

**参照箇所:**
```python
models_resp = client.table("vehicle_models").select("id,name,manufacturer_id,category_code").eq("is_active", True).order("display_order").execute()
```

**想定カラム:** id, name, manufacturer_id, category_code, is_active, display_order

---

## 10. 既知の制限事項と未実装機能

### 10.1 スキーマとコードの不整合

1. **simulations テーブル:** API層（`SimulationRepository`）は `input_data` (jsonb), `result` (jsonb) カラムを使用しているが、マイグレーションSQLではこれらのカラムが定義されていない（代わりに `result_summary_json` がある）。本番DBではマイグレーション外で追加されている可能性がある。

2. **equipment_options テーブル:** コード内で参照されているがマイグレーションSQLに含まれていない。

3. **vehicle_models テーブル:** 同上。

### 10.2 ファンド管理機能

DBスキーマ（`20260406000000_create_fund_management.sql`）で以下のテーブルが定義されているが、対応するAPIエンドポイントやUI画面は未実装:
- funds（ファンド/SPC管理）
- fund_investors（投資家管理）
- lease_contracts（リース契約管理）
- lease_payments（リース支払管理）
- secured_asset_blocks（SAB: 担保資産ブロック）
- fee_records（手数料記録）
- fund_distributions（分配金記録）

これらのテーブルにはRLSポリシーも未定義。

### 10.3 未実装のUI機能

1. **パスワードリセット:** ログイン画面に「パスワードを忘れた方」リンク（`/auth/forgot-password`）があるが、エンドポイントは未実装。

2. **ユーザー管理画面:** admin向けのユーザーCRUD画面は存在しない。

3. **相場データ統計ダッシュボード:** API（`/api/v1/market-prices/statistics`）は実装済みだが、専用のビジュアライゼーション画面は未実装。

4. **シミュレーション比較UI:** API（`POST /api/v1/simulations/compare`）は実装済みだが、比較結果を表示する画面は未実装。

5. **シミュレーション履歴画面:** API（`GET /api/v1/simulations`）とHTMLフラグメント生成は実装済みだが、`/simulations` ページ自体のルートは未定義。

### 10.4 スクレイピングの制限

1. **手動実行のみ:** cronジョブやスケジューラの自動実行設定は含まれていない。
2. **管理UI無し:** スクレイピングジョブの実行・監視UIは未実装。
3. **CSS セレクタの脆弱性:** 対象サイトのDOM構造変更に対してフォールバックセレクタを多数用意しているが、サイト大幅リニューアル時は要更新。

### 10.5 セキュリティ関連

1. **CORS設定:** localhost:8000, localhost:3000, Supabase URLのみ許可。本番ドメインの明示的な追加が必要な場合がある。
2. **CSRF:** メタタグでトークンを設定するコードがテンプレートにあるが、バックエンドでの検証は未実装。
3. **Quick Calculation認証:** `POST /api/v1/simulations/calculate` は認証不要。意図的な設計だが、API乱用リスクがある。

### 10.6 その他

1. **vehicles テーブルの legacy フィールド:** 市場価格API（`market_prices.py`）では `maker`, `body_type`, `listing_status` を直接文字列カラムとして検索しているが、DBスキーマでは外部キー（`manufacturer_id`, `body_type_id`）で管理。スクレイパーは `maker` 等の文字列フィールドもDBに書き込んでいるため、テーブルには`maker`カラムが追加されている可能性がある（マイグレーション外）。

2. **ページネーション:** 相場データ一覧のページネーションはHTMXフラグメントで実装されているが、ページ番号のナビゲーションUIは限定的。

3. **テスト:** `_max_purchase_price`, `_residual_value`, `_monthly_lease_fee`, `_assessment`, `_build_schedule` はテスト互換のための薄いラッパー関数として明示的に維持されている（「Backward-compatible thin wrappers used by unit tests」とコメントあり）。

---

## 付録: CSSテーマ変数

```css
:root {
  --primary: #2563eb;
  --primary-hover: #1d4ed8;
  --danger: #dc2626;
  --success: #16a34a;
  --warning: #f59e0b;
  --info: #0ea5e9;
  --bg: #f8fafc;
  --text: #1e293b;
  --text-muted: #64748b;
  --border: #e2e8f0;
  --sidebar-width: 240px;
  --header-height: 56px;
  --font-sans: "Inter", "Noto Sans JP", -apple-system, ...;
  --font-mono: "JetBrains Mono", "Fira Code", ...;
}
```
