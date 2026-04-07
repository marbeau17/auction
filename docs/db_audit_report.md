# データベース監査レポート

**監査日時**: 2026年4月6日  
**対象**: Supabase PostgreSQL (`db.yafgmwqgaefitbvfzowh.supabase.co`)  
**データベース名**: `postgres`  
**スキーマ**: `public`

---

## 1. テーブル一覧とレコード数

| # | テーブル名 | レコード数 | 説明 |
|---|-----------|-----------|------|
| 1 | `body_types` | 10 | 車体形状マスタ |
| 2 | `depreciation_curves` | 10 | 減価償却カーブ |
| 3 | `equipment_options` | 22 | 装備オプションマスタ |
| 4 | `manufacturers` | 4 | メーカーマスタ |
| 5 | `scraping_logs` | 14 | スクレイピング実行ログ |
| 6 | `simulation_params` | 120 | シミュレーションパラメータ |
| 7 | `simulations` | 15 | シミュレーション |
| 8 | `users` | 2 | ユーザー |
| 9 | `vehicle_categories` | 5 | 車両カテゴリマスタ |
| 10 | `vehicle_models` | 12 | 車両モデルマスタ |
| 11 | `vehicle_price_history` | 20 | 車両価格履歴 |
| 12 | `vehicles` | 64 | 車両データ |

**合計**: 12テーブル / 296レコード

---

## 2. テーブル別カラム定義

### 2.1 `body_types` (車体形状マスタ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `name` | text | NO | - |
| `code` | text | NO | - |
| `category_id` | uuid | YES | - |
| `display_order` | integer | NO | `0` |
| `is_active` | boolean | NO | `true` |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.2 `depreciation_curves` (減価償却カーブ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `category_id` | uuid | NO | - |
| `manufacturer_id` | uuid | YES | - |
| `body_type_id` | uuid | YES | - |
| `curve_type` | text | NO | `'linear'` |
| `useful_life_years` | integer | NO | - |
| `residual_rate` | numeric | NO | `0.1000` |
| `custom_curve_json` | jsonb | YES | - |
| `effective_from` | date | NO | `CURRENT_DATE` |
| `effective_to` | date | YES | - |
| `notes` | text | YES | - |
| `created_by` | uuid | YES | - |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.3 `equipment_options` (装備オプションマスタ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `name` | text | NO | - |
| `name_en` | text | YES | - |
| `category` | text | NO | - |
| `estimated_value_yen` | integer | YES | `0` |
| `depreciation_rate` | numeric | YES | `0.150` |
| `affects_lease_price` | boolean | YES | `true` |
| `display_order` | integer | YES | `0` |
| `is_active` | boolean | YES | `true` |
| `created_at` | timestamp with time zone | YES | `now()` |
| `updated_at` | timestamp with time zone | YES | `now()` |

### 2.4 `manufacturers` (メーカーマスタ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `name` | text | NO | - |
| `name_en` | text | YES | - |
| `code` | text | NO | - |
| `country` | text | NO | `'JP'` |
| `display_order` | integer | NO | `0` |
| `is_active` | boolean | NO | `true` |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.5 `scraping_logs` (スクレイピング実行ログ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `source_site` | text | NO | - |
| `status` | text | NO | `'running'` |
| `started_at` | timestamp with time zone | NO | `now()` |
| `finished_at` | timestamp with time zone | YES | - |
| `total_pages` | integer | YES | - |
| `processed_pages` | integer | NO | `0` |
| `new_records` | integer | NO | `0` |
| `updated_records` | integer | NO | `0` |
| `skipped_records` | integer | NO | `0` |
| `error_count` | integer | NO | `0` |
| `error_details` | jsonb | YES | - |
| `triggered_by` | text | NO | `'cron'` |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.6 `simulation_params` (シミュレーションパラメータ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `simulation_id` | uuid | NO | - |
| `param_key` | text | NO | - |
| `param_value` | numeric | YES | - |
| `param_unit` | text | YES | - |
| `description` | text | YES | - |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.7 `simulations` (シミュレーション)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `user_id` | uuid | NO | - |
| `title` | text | YES | - |
| `category_id` | uuid | YES | - |
| `manufacturer_id` | uuid | YES | - |
| `body_type_id` | uuid | YES | - |
| `target_model_name` | text | YES | - |
| `target_model_year` | integer | YES | - |
| `target_mileage_km` | integer | YES | - |
| `market_price_yen` | bigint | YES | - |
| `purchase_price_yen` | bigint | YES | - |
| `lease_monthly_yen` | bigint | YES | - |
| `lease_term_months` | integer | YES | - |
| `total_lease_revenue_yen` | bigint | YES | - |
| `expected_yield_rate` | numeric | YES | - |
| `result_summary_json` | jsonb | YES | - |
| `status` | text | NO | `'draft'` |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.8 `users` (ユーザー)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `email` | text | NO | - |
| `full_name` | text | NO | - |
| `role` | text | NO | `'sales'` |
| `department` | text | YES | - |
| `is_active` | boolean | NO | `true` |
| `last_signed_in_at` | timestamp with time zone | YES | - |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.9 `vehicle_categories` (車両カテゴリマスタ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `name` | text | NO | - |
| `code` | text | NO | - |
| `display_order` | integer | NO | `0` |
| `is_active` | boolean | NO | `true` |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |

### 2.10 `vehicle_models` (車両モデルマスタ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `manufacturer_id` | uuid | NO | - |
| `name` | text | NO | - |
| `name_en` | text | YES | - |
| `category_code` | text | YES | - |
| `display_order` | integer | YES | `0` |
| `is_active` | boolean | YES | `true` |
| `created_at` | timestamp with time zone | YES | `now()` |
| `updated_at` | timestamp with time zone | YES | `now()` |

### 2.11 `vehicle_price_history` (車両価格履歴)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | bigint | NO | `nextval('vehicle_price_history_id_seq')` |
| `source_site` | character varying | NO | - |
| `source_vehicle_id` | character varying | NO | - |
| `price_yen` | integer | NO | - |
| `price_tax_included` | boolean | YES | - |
| `observed_at` | timestamp with time zone | NO | `now()` |

### 2.12 `vehicles` (車両データ)

| カラム名 | データ型 | NULL許可 | デフォルト値 |
|---------|---------|---------|-------------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `source_site` | text | NO | - |
| `source_url` | text | YES | - |
| `source_id` | text | YES | - |
| `category_id` | uuid | NO | - |
| `manufacturer_id` | uuid | NO | - |
| `body_type_id` | uuid | YES | - |
| `model_name` | text | NO | - |
| `model_year` | integer | YES | - |
| `mileage_km` | integer | YES | - |
| `price_yen` | bigint | YES | - |
| `price_tax_included` | boolean | NO | `false` |
| `tonnage` | numeric | YES | - |
| `engine_displacement_cc` | integer | YES | - |
| `transmission` | text | YES | - |
| `fuel_type` | text | YES | - |
| `location_prefecture` | text | YES | - |
| `image_url` | text | YES | - |
| `scraped_at` | timestamp with time zone | NO | `now()` |
| `is_active` | boolean | NO | `true` |
| `created_at` | timestamp with time zone | NO | `now()` |
| `updated_at` | timestamp with time zone | NO | `now()` |
| `maker` | text | YES | - |
| `body_type` | text | YES | - |

---

## 3. 外部キー関係 (リレーションシップ)

| テーブル | カラム | 参照先テーブル | 参照先カラム |
|---------|--------|-------------|-------------|
| `body_types` | `category_id` | `vehicle_categories` | `id` |
| `vehicles` | `category_id` | `vehicle_categories` | `id` |
| `vehicles` | `manufacturer_id` | `manufacturers` | `id` |
| `vehicles` | `body_type_id` | `body_types` | `id` |
| `vehicle_models` | `manufacturer_id` | `manufacturers` | `id` |
| `depreciation_curves` | `category_id` | `vehicle_categories` | `id` |
| `depreciation_curves` | `manufacturer_id` | `manufacturers` | `id` |
| `depreciation_curves` | `body_type_id` | `body_types` | `id` |
| `depreciation_curves` | `created_by` | `users` | `id` |
| `simulations` | `user_id` | `users` | `id` |
| `simulations` | `category_id` | `vehicle_categories` | `id` |
| `simulations` | `manufacturer_id` | `manufacturers` | `id` |
| `simulations` | `body_type_id` | `body_types` | `id` |
| `simulation_params` | `simulation_id` | `simulations` | `id` |

### ER関係図 (テキスト表現)

```
users
  |-- simulations (user_id)
  |-- depreciation_curves (created_by)

vehicle_categories
  |-- body_types (category_id)
  |-- vehicles (category_id)
  |-- simulations (category_id)
  |-- depreciation_curves (category_id)

manufacturers
  |-- vehicles (manufacturer_id)
  |-- vehicle_models (manufacturer_id)
  |-- simulations (manufacturer_id)
  |-- depreciation_curves (manufacturer_id)

body_types
  |-- vehicles (body_type_id)
  |-- simulations (body_type_id)
  |-- depreciation_curves (body_type_id)

simulations
  |-- simulation_params (simulation_id)
```

---

## 4. インデックス一覧

### 4.1 `body_types`

| インデックス名 | 定義 |
|---------------|------|
| `body_types_pkey` | UNIQUE btree (`id`) |
| `body_types_code_key` | UNIQUE btree (`code`) |
| `idx_body_types_category_id` | btree (`category_id`) |

### 4.2 `depreciation_curves`

| インデックス名 | 定義 |
|---------------|------|
| `depreciation_curves_pkey` | UNIQUE btree (`id`) |
| `idx_depreciation_curves_category` | btree (`category_id`) |
| `idx_depreciation_curves_effective` | btree (`effective_from`, `effective_to`) |

### 4.3 `equipment_options`

| インデックス名 | 定義 |
|---------------|------|
| `equipment_options_pkey` | UNIQUE btree (`id`) |

### 4.4 `manufacturers`

| インデックス名 | 定義 |
|---------------|------|
| `manufacturers_pkey` | UNIQUE btree (`id`) |
| `manufacturers_code_key` | UNIQUE btree (`code`) |

### 4.5 `scraping_logs`

| インデックス名 | 定義 |
|---------------|------|
| `scraping_logs_pkey` | UNIQUE btree (`id`) |
| `idx_scraping_logs_source_site` | btree (`source_site`) |
| `idx_scraping_logs_status` | btree (`status`) |
| `idx_scraping_logs_started_at` | btree (`started_at` DESC) |

### 4.6 `simulation_params`

| インデックス名 | 定義 |
|---------------|------|
| `simulation_params_pkey` | UNIQUE btree (`id`) |
| `uq_simulation_params_key` | UNIQUE btree (`simulation_id`, `param_key`) |
| `idx_simulation_params_simulation_id` | btree (`simulation_id`) |

### 4.7 `simulations`

| インデックス名 | 定義 |
|---------------|------|
| `simulations_pkey` | UNIQUE btree (`id`) |
| `idx_simulations_user_id` | btree (`user_id`) |
| `idx_simulations_category` | btree (`category_id`) |
| `idx_simulations_status` | btree (`status`) |
| `idx_simulations_created_at` | btree (`created_at` DESC) |

### 4.8 `users`

| インデックス名 | 定義 |
|---------------|------|
| `users_pkey` | UNIQUE btree (`id`) |
| `users_email_key` | UNIQUE btree (`email`) |

### 4.9 `vehicle_categories`

| インデックス名 | 定義 |
|---------------|------|
| `vehicle_categories_pkey` | UNIQUE btree (`id`) |
| `vehicle_categories_code_key` | UNIQUE btree (`code`) |

### 4.10 `vehicle_models`

| インデックス名 | 定義 |
|---------------|------|
| `vehicle_models_pkey` | UNIQUE btree (`id`) |
| `idx_vehicle_models_mfr` | btree (`manufacturer_id`) |

### 4.11 `vehicle_price_history`

| インデックス名 | 定義 |
|---------------|------|
| `vehicle_price_history_pkey` | UNIQUE btree (`id`) |
| `idx_vehicle_price_history_source` | btree (`source_site`, `source_vehicle_id`) |
| `idx_vehicle_price_history_observed_at` | btree (`observed_at` DESC) |

### 4.12 `vehicles`

| インデックス名 | 定義 |
|---------------|------|
| `vehicles_pkey` | UNIQUE btree (`id`) |
| `uq_vehicles_source` | UNIQUE btree (`source_site`, `source_id`) |
| `idx_vehicles_category_id` | btree (`category_id`) |
| `idx_vehicles_manufacturer_id` | btree (`manufacturer_id`) |
| `idx_vehicles_body_type_id` | btree (`body_type_id`) |
| `idx_vehicles_model_year` | btree (`model_year`) |
| `idx_vehicles_price_yen` | btree (`price_yen`) |
| `idx_vehicles_scraped_at` | btree (`scraped_at` DESC) |
| `idx_vehicles_search_composite` | btree (`category_id`, `manufacturer_id`, `body_type_id`, `model_year`, `price_yen`) WHERE `is_active = true` |

---

## 5. RLS (Row Level Security) ポリシー

### RLS有効化状況

| テーブル | RLS有効 | 備考 |
|---------|---------|------|
| `body_types` | 有効 | |
| `depreciation_curves` | 有効 | |
| `equipment_options` | **無効** | ポリシー未設定 |
| `manufacturers` | 有効 | |
| `scraping_logs` | 有効 | |
| `simulation_params` | 有効 | |
| `simulations` | 有効 | |
| `users` | 有効 | |
| `vehicle_categories` | 有効 | |
| `vehicle_models` | **無効** | ポリシー未設定 |
| `vehicle_price_history` | 有効 | |
| `vehicles` | 有効 | |

### ポリシー詳細

#### `body_types`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `body_types_select` | SELECT | `true` (全員閲覧可) |
| `body_types_insert` | INSERT | `current_user_role() = 'admin'` |
| `body_types_update` | UPDATE | `current_user_role() = 'admin'` |
| `body_types_delete` | DELETE | `current_user_role() = 'admin'` |

#### `depreciation_curves`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `depreciation_curves_select` | SELECT | `true` (全員閲覧可) |
| `depreciation_curves_insert` | INSERT | `current_user_role() = 'admin'` |
| `depreciation_curves_update` | UPDATE | `current_user_role() = 'admin'` |
| `depreciation_curves_delete` | DELETE | `current_user_role() = 'admin'` |

#### `manufacturers`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `manufacturers_select` | SELECT | `true` (全員閲覧可) |
| `manufacturers_insert` | INSERT | `current_user_role() = 'admin'` |
| `manufacturers_update` | UPDATE | `current_user_role() = 'admin'` |
| `manufacturers_delete` | DELETE | `current_user_role() = 'admin'` |

#### `scraping_logs`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `scraping_logs_select` | SELECT | `current_user_role() = 'admin'` |
| `scraping_logs_insert_service` | INSERT | `auth.role() = 'service_role'` |
| `scraping_logs_update_service` | UPDATE | `auth.role() = 'service_role'` |

#### `simulation_params`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `simulation_params_select` | SELECT | 自分のシミュレーション or admin |
| `simulation_params_insert` | INSERT | 自分のシミュレーション |
| `simulation_params_update` | UPDATE | 自分のシミュレーション |
| `simulation_params_delete` | DELETE | 自分のシミュレーション |

#### `simulations`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `simulations_select` | SELECT | `user_id = auth.uid()` or admin |
| `simulations_insert` | INSERT | `user_id = auth.uid()` |
| `simulations_update` | UPDATE | `user_id = auth.uid()` |
| `simulations_delete` | DELETE | `user_id = auth.uid()` |

#### `users`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `users_select_own` | SELECT | `id = auth.uid()` or admin |
| `users_update_own` | UPDATE | `id = auth.uid()` or admin |
| `users_insert_admin` | INSERT | `current_user_role() = 'admin'` |
| `users_delete_admin` | DELETE | `current_user_role() = 'admin'` |

#### `vehicle_categories`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `vehicle_categories_select` | SELECT | `true` (全員閲覧可) |
| `vehicle_categories_insert` | INSERT | `current_user_role() = 'admin'` |
| `vehicle_categories_update` | UPDATE | `current_user_role() = 'admin'` |
| `vehicle_categories_delete` | DELETE | `current_user_role() = 'admin'` |

#### `vehicle_price_history`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `vehicle_price_history_select` | SELECT | `current_user_role() = 'admin'` |
| `vehicle_price_history_insert_service` | INSERT | `auth.role() = 'service_role'` |

#### `vehicles`

| ポリシー名 | 操作 | 条件 |
|-----------|------|------|
| `vehicles_select` | SELECT | `true` (全員閲覧可) |
| `vehicles_insert_service` | INSERT | `auth.role() = 'service_role'` |
| `vehicles_update_service` | UPDATE | `auth.role() = 'service_role'` |
| `vehicles_delete_service` | DELETE | `auth.role() = 'service_role'` |

---

## 6. トリガー

全テーブルに `updated_at` 自動更新トリガーが設定されている。

| トリガー名 | 対象テーブル | イベント | 実行関数 |
|-----------|------------|---------|---------|
| `trg_body_types_updated_at` | `body_types` | UPDATE | `set_updated_at()` |
| `trg_depreciation_curves_updated_at` | `depreciation_curves` | UPDATE | `set_updated_at()` |
| `trg_equipment_options_updated_at` | `equipment_options` | UPDATE | `set_updated_at()` |
| `trg_manufacturers_updated_at` | `manufacturers` | UPDATE | `set_updated_at()` |
| `trg_scraping_logs_updated_at` | `scraping_logs` | UPDATE | `set_updated_at()` |
| `trg_simulation_params_updated_at` | `simulation_params` | UPDATE | `set_updated_at()` |
| `trg_simulations_updated_at` | `simulations` | UPDATE | `set_updated_at()` |
| `trg_users_updated_at` | `users` | UPDATE | `set_updated_at()` |
| `trg_vehicle_categories_updated_at` | `vehicle_categories` | UPDATE | `set_updated_at()` |
| `trg_vehicle_models_updated_at` | `vehicle_models` | UPDATE | `set_updated_at()` |
| `trg_vehicles_updated_at` | `vehicles` | UPDATE | `set_updated_at()` |

---

## 7. カスタム関数

| 関数名 | 種別 | 戻り値型 | 用途 |
|--------|------|---------|------|
| `current_user_role()` | FUNCTION | text | RLSポリシーで使用。現在のユーザーのロールを返す |
| `set_updated_at()` | FUNCTION | trigger | `updated_at` カラムを自動更新 |

---

## 8. マスタデータの内容

### 8.1 メーカー (`manufacturers`) - 4件

| メーカー名 | コード |
|-----------|--------|
| いすゞ | ISZ |
| 日野 | HNO |
| 三菱ふそう | MFU |
| UDトラックス | UDT |

### 8.2 車体形状 (`body_types`) - 10件

| 車体形状名 | コード |
|-----------|--------|
| ウイング | WING |
| バン | VAN |
| 平ボディ | FLAT |
| 冷凍冷蔵車 | REFR |
| ダンプ | DUMP |
| クレーン付き | CRAN |
| タンクローリー | TANK |
| 塵芥車 | TRSH |
| ミキサー | MIXR |
| キャリアカー | CARR |

### 8.3 車両カテゴリ (`vehicle_categories`) - 5件

| カテゴリ名 | コード |
|-----------|--------|
| 大型トラック | LARGE |
| 中型トラック | MEDIUM |
| 小型トラック | SMALL |
| トレーラーヘッド | TRAILER_HEAD |
| トレーラーシャシー | TRAILER_CHASSIS |

### 8.4 車両モデル (`vehicle_models`) - 12件

| モデル名 | カテゴリ | メーカー |
|---------|---------|---------|
| プロフィア | LARGE | 日野 |
| レンジャー | MEDIUM | 日野 |
| デュトロ | SMALL | 日野 |
| クオン | LARGE | UDトラックス |
| コンドル | MEDIUM | UDトラックス |
| カゼット | SMALL | UDトラックス |
| スーパーグレート | LARGE | 三菱ふそう |
| ファイター | MEDIUM | 三菱ふそう |
| キャンター | SMALL | 三菱ふそう |
| ギガ | LARGE | いすゞ |
| フォワード | MEDIUM | いすゞ |
| エルフ | SMALL | いすゞ |

### 8.5 装備オプション (`equipment_options`) - 22件

#### comfort (快適装備)

| オプション名 | 推定価値(円) |
|-------------|------------|
| エアサス（全輪） | 500,000 |
| リターダ | 350,000 |
| アルミホイール | 200,000 |
| ハイルーフキャブ | 150,000 |

#### crane (クレーン)

| オプション名 | 推定価値(円) |
|-------------|------------|
| 小型クレーン（2.9t吊） | 1,500,000 |
| 中型クレーン（4.9t吊） | 2,500,000 |
| ラジコン操作装置 | 300,000 |

#### loading (積載)

| オプション名 | 推定価値(円) |
|-------------|------------|
| パワーゲート | 350,000 |
| 床フック・ラッシングレール | 80,000 |
| ジョルダー（荷寄せ装置） | 200,000 |
| ウイング開閉装置（電動） | 150,000 |

#### other (その他)

| オプション名 | 推定価値(円) |
|-------------|------------|
| ETC車載器 | 30,000 |
| アルミウイングボディ（特注） | 800,000 |
| ステンレス製荷台 | 400,000 |

#### refrigeration (冷凍冷蔵)

| オプション名 | 推定価値(円) |
|-------------|------------|
| 冷凍ユニット（-25度） | 1,200,000 |
| 冷蔵ユニット（+5度） | 800,000 |
| 二温度帯仕様 | 1,800,000 |
| スタンバイ電源装置 | 250,000 |

#### safety (安全装備)

| オプション名 | 推定価値(円) |
|-------------|------------|
| バックカメラ | 80,000 |
| ドライブレコーダー | 50,000 |
| 衝突被害軽減ブレーキ | 200,000 |
| 車線逸脱警報装置 | 120,000 |

---

## 9. 監査所見

### 9.1 セキュリティに関する所見

| # | 重要度 | 内容 |
|---|-------|------|
| 1 | **警告** | `equipment_options` テーブルのRLSが**無効**。誰でもINSERT/UPDATE/DELETEが可能 |
| 2 | **警告** | `vehicle_models` テーブルのRLSが**無効**。誰でもINSERT/UPDATE/DELETEが可能 |
| 3 | 情報 | `vehicle_price_history` にはUPDATE/DELETEポリシーが未定義（service_roleのみINSERT可） |
| 4 | 情報 | `scraping_logs` にはDELETEポリシーが未定義 |

### 9.2 スキーマに関する所見

| # | 内容 |
|---|------|
| 1 | `vehicles` テーブルに `maker` (text) と `body_type` (text) カラムが存在する。これらは `manufacturer_id` / `body_type_id` の外部キーと**重複**しており、データ整合性リスクがある |
| 2 | `vehicle_price_history` の `id` は `bigint` (シーケンス) を使用しており、他テーブルの `uuid` 方式と異なる |
| 3 | `vehicle_price_history` には `vehicle_id` (外部キー) がなく、`source_site` + `source_vehicle_id` で `vehicles` テーブルと紐付ける設計 |
| 4 | `vehicle_models` の `category_code` は外部キーではなく、`vehicle_categories.code` とのテキスト参照になっている |

### 9.3 データ量に関する所見

| # | 内容 |
|---|------|
| 1 | 全体のデータ量は296レコードと少なく、開発初期段階と推測される |
| 2 | `vehicles` 64件、`simulations` 15件、`simulation_params` 120件 (平均8パラメータ/シミュレーション) |
| 3 | ユーザーは2名のみ登録 |

---

*以上*
