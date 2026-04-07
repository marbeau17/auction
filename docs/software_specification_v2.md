# 商用車リースバック価格最適化システム（CVLPOS）
# ソフトウェア開発仕様書

**バージョン:** 2.0  
**作成日:** 2026年4月7日  
**本番URL:** https://auction-ten-iota.vercel.app  
**GitHub:** https://github.com/marbeau17/auction  

---

## 目次

1. システム概要
2. 認証・認可システム
3. データベーススキーマ
4. 画面一覧とUI設計
5. 計算ロジック
6. APIエンドポイント一覧
7. ビジュアライゼーション
8. スクレイピングシステム
9. 装備オプション・車種マスタ
10. テスト・CI/CD
11. あるべき姿（将来ビジョン）

---

## 1. システム概要

### 1.1 システム名称と目的

- **システム名称**: CVLPOS — Commercial Vehicle Leaseback Pricing Optimizer
- **プロジェクト名**: `auction` (v0.1.0)
- **目的**: 商用車両（トラック等）のリースバック価格を最適化するためのWebアプリケーション。市場価格データの収集・分析、シミュレーション、ダッシュボードによる可視化機能を提供する。

### 1.2 技術スタック（実装済み）

| カテゴリ | 技術 | バージョン要件 |
|---|---|---|
| 言語 | Python | >= 3.11 |
| Webフレームワーク | FastAPI | >= 0.104.0 |
| ASGIサーバー | Uvicorn (standard) | >= 0.24.0 |
| テンプレートエンジン | Jinja2 | >= 3.1.0 |
| フロントエンド（動的UI） | HTMX | （静的ファイルとして配信） |
| チャート描画 | Chart.js | （静的ファイルとして配信） |
| データベース / BaaS | Supabase (supabase-py) | >= 2.0.0 |
| HTTPクライアント | httpx | >= 0.25.0 |
| 設定管理 | pydantic-settings | >= 2.0.0 |
| 認証 (JWT) | python-jose[cryptography] | >= 3.3.0 |
| パスワードハッシュ | passlib[bcrypt] | >= 1.7.4 |
| ログ | structlog | >= 23.0.0 |
| キャッシュ | cachetools | >= 5.3.0 |
| 数値計算 | numpy | >= 1.24.0 |
| スクレイピング | beautifulsoup4 (>= 4.12.0), lxml (>= 4.9.0) | コア依存 |
| スクレイピング（ブラウザ） | Playwright | >= 1.40.0 (optional: `scraper`) |
| レポート生成 | pandas (>= 2.0.0), openpyxl (>= 3.1.0), reportlab (>= 4.0.0) | optional: `report` |
| フォームパース | python-multipart | >= 0.0.6 |
| ビルドシステム | Hatchling | — |

### 1.3 デプロイ構成

#### 本番環境（Vercel）

| 項目 | 値 |
|---|---|
| 本番URL | https://auction-ten-iota.vercel.app |
| GitHub リポジトリ | https://github.com/marbeau17/auction |
| ランタイム | `@vercel/python` (Serverless Functions) |
| エントリポイント | `api/index.py` |
| Lambda最大サイズ | 50MB |
| 静的ファイル配信 | `@vercel/static` (`/static/**`) |
| ルーティング | `/static/*` は静的配信、それ以外は全て `api/index.py` へプロキシ |

#### Render構成（render.yaml 定義済み）

| サービス | 種別 | ランタイム | 備考 |
|---|---|---|---|
| `auction-web` | Web Service | Docker | ポート8000、ヘルスチェック `/health`、自動デプロイ有効 |
| `auction-scraper` | Cron Job | Docker | 毎日 03:00 UTC 実行、`python -m scraper.run` |

#### Docker構成

- ベースイメージ: `python:3.11-slim`
- Chromium（Playwright用）をインストール済み
- 実行コマンド: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

#### データベース

- **Supabase PostgreSQL**（東京リージョン）
- 接続: `DATABASE_URL` 環境変数による直接接続、および Supabase クライアントSDK経由のAPI接続

### 1.4 ミドルウェア構成

ミドルウェアは `create_app()` 内で以下の順序で登録される（リクエスト処理は登録の逆順）:

#### 1. CORS（CORSMiddleware）

| 設定項目 | 値 |
|---|---|
| 許可オリジン | `http://localhost:{APP_PORT}`, `http://localhost:3000`, `https://auction-ten-iota.vercel.app`, Supabase URL |
| 認証情報 | `allow_credentials=True` |
| 許可メソッド | GET, POST, PUT, DELETE, OPTIONS |
| 許可ヘッダー | Content-Type, Authorization, X-CSRF-Token, HX-Request, HX-Target, HX-Trigger |

#### 2. セキュリティヘッダー（カスタムHTTPミドルウェア）

全レスポンスに以下のヘッダーを付与:

| ヘッダー | 値 |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

#### 3. CSRF（CSRFMiddleware）

- `app.middleware.csrf.CSRFMiddleware` として実装
- `X-CSRF-Token` ヘッダーによるトークン検証（CORSの許可ヘッダーに含まれている）

### 1.5 環境変数一覧

| 環境変数名 | Settings属性 | デフォルト値 | 説明 |
|---|---|---|---|
| `APP_ENV` | `app_env` | `"development"` | 実行環境（development / production） |
| `APP_DEBUG` | `app_debug` | `False` | デバッグモード |
| `APP_PORT` | `app_port` | `8000` | アプリケーションポート |
| `APP_SECRET_KEY` | `app_secret_key` | `"change-me"` | アプリケーション秘密鍵（CSRF等） |
| `SUPABASE_URL` | `supabase_url` | `""` | Supabase プロジェクトURL |
| `SUPABASE_ANON_KEY` | `supabase_anon_key` | `""` | Supabase 匿名キー |
| `SUPABASE_SERVICE_ROLE_KEY` | `supabase_service_role_key` | `""` | Supabase サービスロールキー |
| `DATABASE_URL` | `database_url` | `""` | PostgreSQL 接続文字列 |
| `SUPABASE_JWT_SECRET` | `supabase_jwt_secret` | `""` | JWT 検証用シークレット |
| `SCRAPER_REQUEST_INTERVAL_SEC` | `scraper_request_interval_sec` | `3` | スクレイパーのリクエスト間隔（秒） |
| `SCRAPER_MAX_RETRIES` | `scraper_max_retries` | `3` | スクレイパーの最大リトライ回数 |
| `SCRAPER_USER_AGENT` | `scraper_user_agent` | `"CommercialVehicleResearchBot/1.0"` | スクレイパーのUser-Agent文字列 |

環境変数は `.env` ファイル（UTF-8）から読み込み可能。`pydantic-settings` の `BaseSettings` により自動バインドされる。

## 2. 認証・認可システム

### 2.1 認証方式

本システムは **Supabase Auth** を認証基盤として採用している。JWT（JSON Web Token）の検証は2つのアルゴリズムに対応する。

| アルゴリズム | 方式 | 検証キー |
|---|---|---|
| **ES256** | 非対称鍵（Supabase デフォルト） | JWKS エンドポイント（`{supabase_url}/auth/v1/.well-known/jwks.json`） |
| **HS256** | 対称鍵（レガシー） | `SUPABASE_JWT_SECRET` 環境変数 |

- JWTヘッダーの `alg` フィールドを確認し、自動的に検証方式を切り替える
- JWKS は `TTLCache` により **1時間キャッシュ**される（`cachetools.TTLCache(maxsize=1, ttl=3600)`）
- ES256の場合は `audience="authenticated"` を検証、HS256の場合はaudience検証をスキップ
- トークンの `sub` クレームからユーザーID、`email` からメールアドレス、`user_metadata.role` または `role` からロールを取得する

### 2.2 ログインフロー

**エンドポイント:** `POST /auth/login`

```
[ブラウザ] → Form Data (email, password)
    → [FastAPI /auth/login]
        → supabase.auth.sign_in_with_password()
            → [Supabase Auth]
    ← access_token + refresh_token
    ← Set-Cookie (HttpOnly)
    ← 302 Redirect → /dashboard
```

**処理フロー:**

1. フォームデータから `email` と `password` を受信
2. `supabase.auth.sign_in_with_password()` で Supabase に認証リクエスト
3. 認証成功時、セッションから `access_token` と `refresh_token` を取得
4. Cookie にトークンをセット（後述）
5. HTMX リクエストの場合: `HX-Redirect: /dashboard` ヘッダーで応答
6. 通常リクエストの場合: HTTP 302 リダイレクトで `/dashboard` へ遷移

**エラー時:** 日本語エラーメッセージ「メールアドレスまたはパスワードが正しくありません。」を返却。HTMX の場合は `#login-error` の HTML フラグメントとして返す。

**Cookie 設定:**

| Cookie名 | `access_token` | `refresh_token` |
|---|---|---|
| HttpOnly | `True` | `True` |
| Secure | `True` | `True` |
| SameSite | `lax` | `lax` |
| Path | `/` | `/` |

- 両方とも `HttpOnly=True` のため、JavaScriptからは直接アクセス不可（XSS対策）
- `Secure=True` により HTTPS 接続でのみ送信される
- `SameSite=lax` によりクロスサイトの unsafe リクエストでは送信されない

### 2.3 ログアウト

**エンドポイント:** `POST /auth/logout`

1. `supabase.auth.sign_out()` でサーバーサイドのセッションを無効化（ベストエフォート）
2. `access_token` と `refresh_token` の Cookie を削除
3. `/login` へリダイレクト（HTMX: `HX-Redirect`、通常: 302）

### 2.4 パスワードリセット

**ページ表示:** `GET /auth/forgot-password`
- `pages/forgot_password.html` テンプレートを表示

**リセット実行:** `POST /auth/forgot-password`

1. フォームデータから `email` を取得
2. 空の場合: 「メールアドレスを入力してください」エラーを返却
3. `supabase.auth.reset_password_email(email)` でリセットメールを送信
4. **セキュリティ:** メールアドレスの存在有無にかかわらず、常に「リセットリンクをメールに送信しました。メールをご確認ください。」と表示（ユーザー列挙攻撃防止）

### 2.5 ロール定義

システムで使用されるロールは以下の3種類:

| ロール | 説明 |
|---|---|
| `admin` | 管理者。全機能にアクセス可能 |
| `sales` | 営業担当。業務機能にアクセス可能 |
| `viewer` | 閲覧者。参照のみ |

**`require_role` 依存性ファクトリ:**

```python
require_role(roles: list[str]) -> Callable
```

- `get_current_user` で認証済みユーザーを取得した上で、ロールチェックを実行
- ユーザーのロールが指定リストに含まれない場合、`HTTP 403 Forbidden`（`"Insufficient permissions"`）を返却
- エンドポイントでの使用例: `Depends(require_role(["admin", "sales"]))`

**ロール取得の優先順位:**
1. JWTペイロードの `user_metadata.role`
2. JWTペイロードのトップレベル `role`
3. デフォルト値: `"authenticated"`

### 2.6 セッション管理

**JWT有効期限:** Supabase Auth のデフォルト設定に準拠（通常1時間）

**トークンリフレッシュ:** `POST /auth/refresh`

1. Cookie から `refresh_token` を取得
2. `supabase.auth.refresh_session(refresh_token)` で新しいトークンペアを発行
3. 新しい `access_token` と `refresh_token` を Cookie に再セット
4. レスポンス: `{"status": "ok"}`

**リフレッシュ失敗時:** `HTTP 401 Unauthorized` を返却（リフレッシュトークン未提供またはセッション更新失敗）

**`_get_optional_user` 関数（ページレンダリング用）:**
- `app/api/pages.py` で定義
- 認証が不要なページでもユーザー情報を任意取得するためのヘルパー
- Cookie の `access_token` を検証し、失敗時は例外を投げずに `None` を返す
- `get_current_user` と同じ ES256/HS256 デュアル検証ロジックを使用

**現在のユーザー情報取得:** `GET /auth/me`
- `get_current_user` 依存性を使用し、`{id, email, role}` を返却

### 2.7 CSRF保護

**ミドルウェア:** `CSRFMiddleware`（`app/middleware/csrf.py`）

**トークン生成:**
- `secrets.token_urlsafe(32)` で暗号学的に安全なトークンを生成
- Cookie に `csrf_token` が存在しない場合のみ新規生成

**Cookie 設定:**

| 項目 | 値 |
|---|---|
| Cookie名 | `csrf_token` |
| HttpOnly | `False`（JavaScriptから読み取り可能にするため） |
| Secure | `True` |
| SameSite | `lax` |
| Path | `/` |

**検証ルール:**
- **安全なメソッド**（`GET`, `HEAD`, `OPTIONS`）: 検証スキップ
- **除外パス:** `/auth/*` および `/health`（ログイン等は CSRF 検証対象外）
- **検証方法:** `X-CSRF-Token` リクエストヘッダーと Cookie の `csrf_token` を比較
- **現在の状態:** 厳格な強制はまだ有効化されていない（`# TODO: strict enforcement after testing` のコメントあり）

**テンプレートでの使用:**
- `_render` 関数が `csrf_token` をテンプレートコンテキストに自動注入
- `request.cookies.get("csrf_token", "")` で取得

### 2.8 ユーザーアカウント

現在登録されているアカウント:

| メールアドレス | ロール |
|---|---|
| `admin@carchs.com` | admin |
| `sales@carchs.com` | sales |

## 3. データベーススキーマ

### 3.1 テーブル一覧

| テーブル名 | レコード数 | 概要 |
|---|---|---|
| users | 2 | システムユーザー（Supabase Auth連携） |
| manufacturers | 4 | メーカーマスタ（いすゞ、日野、三菱ふそう、UDトラックス） |
| body_types | 10 | 架装タイプマスタ |
| vehicle_categories | 5 | 車両カテゴリマスタ |
| vehicle_models | 12 | 車種マスタ（メーカー別） |
| equipment_options | 22 | 装備オプションマスタ |
| vehicles | 64 | 車両相場データ（スクレイピング取得） |
| simulations | 18 | シミュレーション実行履歴 |
| simulation_params | 120 | シミュレーションパラメータ |
| scraping_logs | 14 | スクレイピング実行ログ |
| depreciation_curves | 10 | 減価償却カーブ設定 |
| vehicle_price_history | 20 | 車両価格変動履歴 |

**合計: 12テーブル、301レコード**

## 4. 画面一覧とUI設計

### 4.1 画面遷移図（テキスト表現）

```
[ログイン画面]
    |
    +---> [パスワードリセット画面] ---> [ログイン画面]
    |
    +---(認証成功)---> [ダッシュボード]
                          |
                          +---> [シミュレーション新規作成] ---> [シミュレーション結果]
                          |         ^                              |
                          |         +------(条件変更して再計算)------+
                          |
                          +---> [シミュレーション履歴一覧] ---> [シミュレーション結果]
                          |
                          +---> [相場データ一覧] ---> [相場データ詳細]
                          |                              |
                          |                              +---> [シミュレーション新規作成]
                          |                                     (車両情報をパラメータで引き継ぎ)
                          |
                          +---> [ログアウト] ---> [ログイン画面]

全画面共通:
  - 401応答 → 自動的に /auth/login へリダイレクト
  - サイドバーから各主要画面へ直接遷移可能
```

### 4.2 各画面の詳細

#### 4.2.1 ログイン画面

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-LOGIN |
| **URL** | `/login` |
| **テンプレート** | `pages/login.html` |
| **認証要否** | 不要（未認証ユーザー向け） |
| **画面の目的** | システムへのユーザー認証 |

**レイアウト構造:**
- base.htmlを継承しない独立レイアウト（`login-page`クラスのbody）
- サイドバーなし、フッターなし
- 中央揃えのカード型フォーム（`login-container` > `login-card`）

**表示データ:**
- ブランドロゴ（トラックアイコン）
- システム名「商用車リースバック価格最適化システム」
- 英語サブタイトル「Commercial Vehicle Leaseback Pricing Optimizer」
- エラーメッセージ表示エリア（`#login-error`、`role="alert"`）

**インタラクティブ要素:**
| 要素 | タイプ | 名前 | バリデーション |
|---|---|---|---|
| メールアドレス | `email` | `email` | required, autocomplete="email" |
| パスワード | `password` | `password` | required, minlength=8 |
| ログイン状態を保持 | `checkbox` | `remember` | 任意 |
| パスワードを忘れた方 | リンク | - | `/auth/forgot-password`へ遷移 |
| ログインボタン | `submit` | - | `btn--primary btn--block btn--lg` |

**HTMX連携:**
- `hx-post="/auth/login"` でフォーム送信
- `hx-target="#login-error"` にエラーメッセージを挿入
- `hx-indicator="#login-spinner"` でスピナー表示
- `hx-disabled-elt="#login-submit"` で送信中はボタン無効化
- CSRFトークンを `X-CSRF-Token` ヘッダーで送信
- 成功時は `HX-Redirect` レスポンスヘッダーでリダイレクト

---

#### 4.2.2 パスワードリセット画面

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-FORGOT-PW |
| **URL** | `/auth/forgot-password` |
| **テンプレート** | `pages/forgot_password.html` |
| **認証要否** | 不要 |
| **画面の目的** | パスワードリセットリンクのメール送信依頼 |

**レイアウト構造:**
- 独立レイアウト（`login-page`クラス、base.html非継承）
- ログイン画面と同じ中央揃えカード型

**表示データ:**
- タイトル「パスワードリセット」
- 説明文「登録メールアドレスにリセットリンクを送信します」
- 結果表示エリア（`#reset-result`）

**インタラクティブ要素:**
| 要素 | タイプ | 名前 | バリデーション |
|---|---|---|---|
| メールアドレス | `email` | `email` | required |
| リセットリンクを送信 | `submit` | - | `btn--primary btn--block btn--lg` |
| ログインに戻る | リンク | - | `/login`へ遷移 |

**HTMX連携:**
- `hx-post="/auth/forgot-password"` でフォーム送信
- `hx-target="#reset-result"` に結果メッセージを挿入

---

#### 4.2.3 ダッシュボード

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-DASHBOARD |
| **URL** | `/dashboard` |
| **テンプレート** | `pages/dashboard.html` |
| **認証要否** | 必要 |
| **画面の目的** | リースバック査定の概況と最新データの一覧表示 |

**レイアウト構造:**
- base.html継承（サイドバー + メインコンテンツ）
- `active_page = 'dashboard'` でサイドバーのダッシュボードリンクがアクティブ

**表示データ:**

**(a) KPIカード（`kpi-grid`セクション、3カード）:**
| カード | アイコンカラー | 表示値 | 単位/補足 |
|---|---|---|---|
| シミュレーション数 | `--primary` | `kpi.simulation_count` | 件 |
| 平均利回り | `--success` | `kpi.avg_yield` | %（小数1桁） |
| 相場変動アラート | `--warning` | `kpi.price_alerts` | 件 + 詳細リンク（件数>0時） |

**(b) クイックアクション（`actions-row`セクション）:**
- 「新規シミュレーション」ボタン（`btn--primary btn--lg`） → `/simulation/new`
- 「相場データ確認」ボタン（`btn--outline btn--lg`） → `/market-data`

**(c) 最近のシミュレーション（`card`セクション）:**
- ヘッダーに「すべて表示」リンク → `/simulations`
- データテーブル（`data-table data-table--hover`）
  - カラム: タイトル / 車種・年式 / 買取価格 / 月額リース / 利回り / ステータス / 実行日
  - 行クリックで `/simulation/{id}/result` へ遷移
  - ステータスバッジ: 完了(success), 承認済(success), 実行中(primary), エラー(danger), 下書き(warning)
- データなし時: 空状態メッセージ「シミュレーション履歴がありません」

**HTMX連携:**
- `#recent-simulations` が `hx-trigger="every 60s"` で60秒ごとに自動リフレッシュ
- `hx-get="/dashboard"` → `hx-select="#recent-simulations"` で部分更新

---

#### 4.2.4 シミュレーション新規作成

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-SIM-NEW |
| **URL** | `/simulation/new` |
| **テンプレート** | `pages/simulation.html` |
| **認証要否** | 必要 |
| **画面の目的** | 車両情報とリース条件を入力して最適な買取価格を算出 |

**レイアウト構造:**
- base.html継承（サイドバー + メインコンテンツ）
- `active_page = 'simulation'`
- 2カラムグリッドレイアウト（`form-grid`）: 左=車両情報、右=リース条件
- レスポンシブ時は1カラムに切り替え

**表示データ / インタラクティブ要素:**

**(a) 車両情報セクション（左カラム）:**
| 要素 | タイプ | 名前 | 必須 | 備考 |
|---|---|---|---|---|
| メーカー | `select` | `maker` | 必須 | サーバーから`makers`リストを取得。変更時にHTMXで車種リスト更新 |
| 車種 | `select` | `model_select` | 必須 | 動的更新。「その他（手動入力）」で自由入力に切替 |
| 車種（手動入力） | `text` | `model_custom` | 条件付き | その他選択時のみ表示 |
| 年式 | `select` | `registration_year_month` | 必須 | 2026年～2010年の範囲 |
| 走行距離 | `number` | `mileage_km` | 必須 | 単位: km |
| クラス | `select` | `vehicle_class` | 必須 | `categories`マスターから取得 |
| ボディタイプ | `select` | `body_type` | 必須 | `body_types`マスターから取得 |
| 取得価格 | `number` | `acquisition_price` | 必須 | 単位: 円 |
| 簿価 | `number` | `book_value` | 必須 | 単位: 円 |

**(b) 装備オプションセクション（左カラム続き）:**
- カテゴリ別チェックボックスグループ（`checkbox-group`）
  - 荷役関連 / クレーン関連 / 冷凍冷蔵関連 / 安全装置 / 快適装備 / その他
- 各チェックボックスに `data-value` 属性で金額を保持
- 「架装オプション合計価格」は選択に応じてJavaScriptで自動計算（`readonly`）

**(c) リース条件セクション（右カラム）:**
| 要素 | タイプ | 名前 | 必須 | 備考 |
|---|---|---|---|---|
| 目標利回り | `number` | `target_yield_rate` | 必須 | step=0.1, 推奨5.0%～15.0%, 初期値8 |
| リース期間 | `select` | `lease_term_months` | 必須 | 12/24/36/48/60ヶ月、初期値24 |

**(d) アクションボタン:**
- 「リセット」ボタン（`btn--outline`, `type="reset"`）
- 「シミュレーション実行」ボタン（`btn--primary btn--lg`）

**HTMX連携:**
- メーカー選択変更時: `hx-get="/api/v1/masters/models-by-maker"` → `#model-select` に車種リスト挿入
- フォーム送信: `hx-post="/api/v1/simulations/calculate"` → `#result-area` に結果表示
- `hx-indicator="#calc-spinner"` で計算中スピナー表示

**クライアントJS:**
- `toggleCustomModel()`: 車種選択で「その他」選択時にテキスト入力を表示切替
- 装備チェックボックスの `change` イベントで合計金額を自動集計

---

#### 4.2.5 シミュレーション履歴一覧

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-SIM-LIST |
| **URL** | `/simulations` |
| **テンプレート** | `pages/simulation_list.html` |
| **認証要否** | 必要 |
| **画面の目的** | 全シミュレーション結果の一覧表示 |

**レイアウト構造:**
- base.html継承（サイドバー + メインコンテンツ）
- ヘッダーに件数表示「全N件のシミュレーション結果」
- アクション行に「新規シミュレーション」ボタン

**表示データ:**
- データテーブル（`data-table`）
  - カラム: タイトル / 車種・年式 / 買取価格 / 月額リース / 利回り / ステータス / 実行日
  - 行クリックで `/simulation/{id}/result` へ遷移
  - ステータスバッジ: 完了(success), 承認済(success), 下書き(warning)
- データなし時: 空状態メッセージ + 新規シミュレーションボタン

**HTMX連携:**
- この画面では特にHTMX連携なし（サーバーサイドレンダリングのみ）

---

#### 4.2.6 シミュレーション結果

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-SIM-RESULT |
| **URL** | `/simulation/{id}/result` |
| **テンプレート** | `pages/simulation_result.html` |
| **認証要否** | 必要 |
| **画面の目的** | 個別シミュレーションの計算結果詳細表示とビジュアル分析 |

**レイアウト構造:**
- base.html継承（サイドバー + メインコンテンツ）
- 上部: ヘッダー（タイトル、ID、日付、ステータスバッジ、評価バッジ）
- KPIカード → 車両情報テーブル → 計算結果テーブル → 装備リスト → チャート群 → アクションボタン

**表示データ:**

**(a) KPIサマリーカード（`kpi-grid`、4カード）:**
| カード | 表示値 |
|---|---|
| 買取価格 | `simulation.purchase_price_yen`（円） |
| 月額リース料 | `simulation.lease_monthly_yen`（円）+ 期間（ヶ月） |
| リース料総額 | `simulation.total_lease_revenue_yen`（円） |
| 想定利回り | `simulation.expected_yield_rate`（%） |

**(b) 車両情報テーブル:**
- メーカー / モデル / 車種名 / ボディタイプ / 車両クラス / 年式 / 走行距離 / 市場参考価格 / 上限価格 / リース期間

**(c) 計算結果詳細テーブル（`result_summary_json`が存在する場合）:**
- 買取価格 / 市場価格 / 月額リース料 / 残価 / 残価率 / 実質利回り / 損益分岐月

**(d) 装備オプションリスト（`simulation.equipment`が存在する場合）:**
- 名称と価格のリスト表示

**(e) Chart.jsによるチャート（`chart_data`が存在する場合、3種類）:**
| チャート | 種類 | 内容 |
|---|---|---|
| バリュートランスファー分析 | 折れ線グラフ | 資産簿価 vs 累積リース収入の推移（高さ350px） |
| NAV推移 | 折れ線グラフ | NAV比率(%) + 60%基準ライン（高さ300px） |
| 月次損益推移 | 棒+折れ線複合 | 月次損益（棒、正負で色分け）+ 累積損益（折れ線）（高さ300px） |

**(f) アクションボタン:**
- 「条件変更して再計算」（`btn--outline`） → `/simulation/new`
- 「ダッシュボードへ」（`btn--primary`） → `/dashboard`

**(g) 結果が見つからない場合:**
- エラーメッセージ + ダッシュボードへ戻るボタン

---

#### 4.2.7 相場データ一覧

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-MARKET-LIST |
| **URL** | `/market-data` |
| **テンプレート** | `pages/market_data_list.html` |
| **認証要否** | 必要 |
| **画面の目的** | 商用車の市場価格データの検索・フィルタリング |

**レイアウト構造:**
- base.html継承（サイドバー + メインコンテンツ）
- `active_page = 'market_data'`
- フィルターバー → データテーブル → ページネーション

**表示データ:**

**(a) フィルターバー（`filter-bar`セクション）:**
| フィルター | タイプ | 名前 | 備考 |
|---|---|---|---|
| メーカー | `select` | `maker` | 「すべて」+ マスターデータ |
| ボディタイプ | `select` | `body_type` | 「すべて」+ マスターデータ |
| 年式（範囲） | `number` x2 | `year_from` / `year_to` | min=2000, max=2026 |
| 価格帯（範囲） | `number` x2 | `price_from` / `price_to` | 単位: 万円, step=10 |
| キーワード | `search` | `keyword` | 車種名など自由検索 |
| フィルターリセット | `button` | - | 全フィルターをクリア |

**(b) データテーブル:**
- カラム: メーカー / 車種 / 年式 / 走行距離 / 価格（税込/税別表示）/ 架装 / 所在地
- 行クリックでHTMXにより詳細画面をメインコンテンツに読み込み
- 価格未設定時は「ASK」と表示
- ローディング中はスピナー + 「データを読み込んでいます...」

**(c) ページネーション:**
- 「前へ / ページ番号 / 次へ」ボタン群
- 現在ページは `btn--primary`、他は `btn--outline`
- 総件数表示（`pagination-bar__info`）

**HTMX連携:**
- 全フィルター要素が `hx-get="/market-data/table"` で `#data-table` を部分更新
- `hx-trigger="change"` でドロップダウン変更時に即座にリクエスト
- キーワードは `hx-trigger="change, keyup changed delay:400ms"` で400msデバウンス
- `hx-include="#filter-form"` で全フィルター値を同時送信
- `hx-indicator="#table-loading"` でローディング表示
- テーブル行クリック: `hx-get="/market-data/{id}"` → `#main-content` に詳細を読み込み + `hx-push-url="true"` でURL更新

---

#### 4.2.8 相場データ詳細

| 項目 | 内容 |
|---|---|
| **画面ID** | SCR-MARKET-DETAIL |
| **URL** | `/market-data/{id}` |
| **テンプレート** | `pages/market_data_detail.html` |
| **認証要否** | 必要 |
| **画面の目的** | 個別車両の市場データ詳細と類似車両の比較 |

**レイアウト構造:**
- base.html継承（サイドバー + メインコンテンツ）
- 戻るリンク付きヘッダー → 価格カード → スペック詳細 → 類似車両テーブル → アクションボタン

**表示データ:**

**(a) ヘッダー（`page-header--with-back`）:**
- 「相場データ一覧」への戻るリンク（SVGアイコン付き）
- 車両名（メーカー + 車種）
- タグ: 年式 / ボディタイプ / 積載量

**(b) 価格カード（`result-card result-card--info`）:**
- 販売価格（税込 or 税別を明示）
- 万円表記への換算値

**(c) 車両スペック（`detail-grid`、定義リスト形式）:**
- メーカー / 車種 / 年式 / 走行距離 / 積載量 / ボディタイプ / ミッション / 燃料 / 所在地 / 掲載ステータス

**(d) 類似車両テーブル（`data-table data-table--hover`）:**
- カラム: メーカー・車種 / 年式 / 走行距離 / 価格 / 詳細リンク
- データなし時: 「類似車両データがありません」

**(e) アクションボタン:**
- 「この車種でシミュレーション」（`btn--primary btn--lg`）
  - クエリパラメータで車両情報（maker, model, body_type, year, price）を引き渡し

**(f) 車両未検出時:**
- エラーメッセージ + 一覧に戻るボタン

---

### 4.3 デザインシステム

#### 4.3.1 カラーパレット

**ブランドカラー:**
| 名前 | CSS変数 | 値 | 用途 |
|---|---|---|---|
| Primary | `--primary` | `#2563eb` (Blue 600) | メインアクション、アクティブ状態、リンク |
| Primary Hover | `--primary-hover` | `#1d4ed8` (Blue 700) | ホバー状態 |
| Primary Light | `--primary-light` | `#dbeafe` (Blue 100) | 背景アクセント |

**セマンティックカラー:**
| 名前 | CSS変数 | 値 | 用途 |
|---|---|---|---|
| Success | `--success` | `#16a34a` (Green 600) | 完了、承認済ステータス |
| Warning | `--warning` | `#f59e0b` (Amber 500) | アラート、下書きステータス |
| Danger | `--danger` | `#dc2626` (Red 600) | エラー、削除 |
| Info | `--info` | `#0ea5e9` (Sky 500) | 情報表示 |

**ニュートラルカラー:**
| 名前 | CSS変数 | ライトモード | ダークモード | 用途 |
|---|---|---|---|---|
| Background | `--bg` | `#f8fafc` | `#0f172a` | ページ背景 |
| Surface | `--bg-white` | `#ffffff` | `#1e293b` | カード・パネル背景 |
| Text | `--text` | `#1e293b` | `#e2e8f0` | 主要テキスト |
| Text Muted | `--text-muted` | `#64748b` | `#94a3b8` | 補助テキスト |
| Text Light | `--text-light` | `#94a3b8` | `#64748b` | 薄いテキスト |
| Border | `--border` | `#e2e8f0` | `#334155` | 境界線 |
| Border Dark | `--border-dark` | `#cbd5e1` | `#475569` | 強調境界線 |

**チャートカラー:**
| 用途 | 色コード |
|---|---|
| 資産簿価 | `#6366f1` (Indigo) |
| 累積リース収入 | `#10b981` (Emerald) |
| NAV比率 | `#2563eb` (Blue) |
| 60%基準ライン | `#f59e0b` (Amber, 破線) |
| 月次損益（正） | `rgba(16,185,129,0.7)` |
| 月次損益（負） | `rgba(239,68,68,0.7)` |
| 累積損益 | `#8b5cf6` (Violet) |

#### 4.3.2 タイポグラフィ

**フォントファミリー:**
- サンセリフ: `Inter`, `Noto Sans JP`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`, sans-serif
- 等幅: `JetBrains Mono`, `Fira Code`, `ui-monospace`, monospace

**フォントサイズスケール:**
| 変数 | サイズ | 用途 |
|---|---|---|
| `--text-xs` | 0.75rem (12px) | テーブルセル（モバイル）、フッター |
| `--text-sm` | 0.875rem (14px) | サイドバーリンク、ラベル、バッジ |
| `--text-base` | 1rem (16px) | 本文テキスト |
| `--text-lg` | 1.125rem (18px) | サイドバーブランド名、セクション見出し |
| `--text-xl` | 1.25rem (20px) | ページタイトル（モバイル） |
| `--text-2xl` | 1.5rem (24px) | ページタイトル |
| `--text-3xl` | 1.875rem (30px) | KPI値 |

**見出し:**
- `font-weight: 600`、`line-height: 1.3`
- 本文: `line-height: 1.6`

#### 4.3.3 コンポーネント

**ボタン（`btn`）:**
| バリアント | クラス | 用途 |
|---|---|---|
| Primary | `btn--primary` | 主要アクション（シミュレーション実行、ログインなど） |
| Outline | `btn--outline` | 副次的アクション（リセット、戻るなど） |
| Text | `btn--text` | テキストリンク風ボタン（フィルターリセット） |
| Block | `btn--block` | 全幅ボタン（ログインフォーム） |
| サイズ | `btn--lg` / `btn--sm` | 大小サイズ |

**カード（`card`）:**
- `card__header`: タイトル + オプションのヘッダーリンク
- `card__body`: コンテンツ領域
- `card__body--flush`: パディングなし（テーブル直接配置用）

**KPIカード（`kpi-card`）:**
- アイコン（カラーバリアント: `--primary`, `--success`, `--warning`）
- ラベル、値、サブテキスト、リンク

**バッジ（`badge`）:**
| バリアント | クラス | 用途 |
|---|---|---|
| Success | `badge--success` | 完了、承認済 |
| Warning | `badge--warning` | 下書き |
| Danger | `badge--danger` | エラー |
| Primary | `badge--primary` | 実行中 |
| Neutral | `badge` (無修飾) | その他 |

**フォーム要素:**
- `form-group`: フォーム項目のラッパー
- `form-label` / `form-label--required`: ラベル（必須マーク付き）
- `form-input` / `form-select` / `form-textarea`: 入力フィールド
- `form-hint`: ヒントテキスト
- `form-checkbox`: チェックボックス + ラベル
- `form-row`: 横並びフォーム行
- `form-grid`: 2カラムフォームレイアウト
- `form-section h3`: セクション見出し（下線にprimaryカラー）

**データテーブル（`data-table`）:**
- `data-table--hover`: ホバー時の行ハイライト
- `data-table__row--clickable`: クリック可能な行（cursor: pointer）
- `table-responsive`: 横スクロール対応ラッパー

**タグ（`tag`）:** 年式やボディタイプの表示用ラベル

**フィルターバー（`filter-bar`）:**
- `filter-form__fields`: フィルター要素の横並びコンテナ
- `filter-form__field--range`: 範囲フィルター（～区切り）
- `filter-form__field--search`: 検索フィールド

**空状態（`empty-state`）:** データなし時のメッセージ表示

**ローディング（`htmx-indicator`）:**
- `spinner`: インラインスピナー
- `loading-placeholder`: フルエリアのローディング表示

**トースト通知（`toast-container` / `toast`）:**
- JavaScriptの `showToast()` で動的生成
- 4.2秒後に自動消去
- `toast-success` / `toast-error` バリアント

**シャドウ:**
| 変数 | 値 | 用途 |
|---|---|---|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | 微細な浮き |
| `--shadow` | 複合 | カード標準 |
| `--shadow-md` | 複合 | 中程度の浮き |
| `--shadow-lg` | 複合 | モーダル・ドロップダウン |

**角丸:**
| 変数 | 値 | 用途 |
|---|---|---|
| `--radius-sm` | 4px | 入力フィールド、バッジ |
| `--radius` | 8px | カード、ボタン |
| `--radius-lg` | 12px | モーダル |

**トランジション:**
| 変数 | 値 | 用途 |
|---|---|---|
| `--transition-fast` | 150ms ease | ホバー効果 |
| `--transition` | 200ms ease | 一般的なアニメーション |
| `--transition-slow` | 300ms ease | サイドバーの開閉 |

---

### 4.4 レスポンシブ対応

3つのブレークポイントで対応:

#### モバイル（< 768px）

| 対象 | 変更内容 |
|---|---|
| サイドバー | `transform: translateX(-100%)` で画面外に隠す。ハンバーガーボタンタップで `.open` クラス付与によりスライドイン |
| サイドバーオーバーレイ | `.sidebar-overlay.active` で半透明黒背景を表示。タップで閉じる |
| メインコンテンツ | `margin-left: 0` でフル幅 |
| ハンバーガーボタン | `display: block` で表示（デスクトップでは非表示） |
| コンテンツパディング | `--space-4` (1rem) に縮小 |
| KPIグリッド | `grid-template-columns: 1fr`（1カラムスタック） |
| フォーム行 | 1カラムスタック |
| フォームグリッド | 1カラムスタック |
| フィルターフォーム | 縦並び（`flex-direction: column`） |
| アクションボタン群 | 縦並び・全幅（`flex-direction: column; align-items: stretch`） |
| データテーブル | `font-size: --text-xs`、パディング縮小 |
| ページタイトル | `--text-xl` に縮小 |
| ヘッダーユーザー名 | `display: none` で非表示 |
| チャートコンテナ | `aspect-ratio: 4/3`, `min-height: 200px` |
| 詳細グリッド | 2カラム |

#### タブレット（768px - 1023px）

| 対象 | 変更内容 |
|---|---|
| KPIグリッド | `grid-template-columns: repeat(2, 1fr)`（2カラム） |

#### デスクトップワイド（1440px+）

| 対象 | 変更内容 |
|---|---|
| コンテンツ | `max-width: 1600px`, `padding: --space-8` (2rem) |

#### モバイルサイドバー制御（app.js）

- ハンバーガーボタンクリックで `.sidebar.open` と `.sidebar-overlay.active` をトグル
- オーバーレイクリックでサイドバーを閉じる
- HTMXリクエスト開始時（`htmx:beforeRequest`）にサイドバーを自動的に閉じる

#### 印刷対応（`@media print`）

- サイドバー、ヘッダー、フッター、ボタン、フィルター、ページネーション、トースト: 非表示
- 背景色・テキスト影・ボックス影を除去
- フォントサイズ10pt
- KPIグリッドは3カラム維持
- カードに `break-inside: avoid` で改ページ防止

---

### 4.5 ダークモード

`@media (prefers-color-scheme: dark)` によるOSレベルの設定に自動追従する。手動切替トグルは未実装。

#### カスタムプロパティの上書き

| 変数 | ライトモード | ダークモード |
|---|---|---|
| `--bg` | `#f8fafc` | `#0f172a` (Slate 900) |
| `--bg-white` | `#ffffff` | `#1e293b` (Slate 800) |
| `--text` | `#1e293b` | `#e2e8f0` (Slate 200) |
| `--text-muted` | `#64748b` | `#94a3b8` (Slate 400) |
| `--text-light` | `#94a3b8` | `#64748b` (Slate 500) |
| `--border` | `#e2e8f0` | `#334155` (Slate 700) |
| `--border-dark` | `#cbd5e1` | `#475569` (Slate 600) |
| `--shadow-*` | 低不透明度 | 高不透明度（より強いシャドウ） |
| セマンティックLight色 | 不透明色 | `rgba()` で20%不透明度 |

#### コンポーネント別のダークモード対応

| コンポーネント | ダークモード時の変更 |
|---|---|
| サイドバー | 背景を `#0c1222`（より深い暗色）に変更 |
| ヘッダー | 背景を `--bg-white`、ボーダーを `--border` に変更 |
| テーブルヘッダー | 背景を `#0f172a` に変更 |
| テーブル行ホバー | `rgba(37,99,235,0.1)` で青系の微かなハイライト |
| ログインページ | グラデーション背景 `#020617 → #0f172a` |
| フォーム入力 | 背景 `#0f172a`、ボーダー `--border`、フォーカス時にブルーグロー |
| Outlineボタン | 背景 `--bg-white`、ボーダー `--border` |
| ページネーション | 背景・ボーダーをダーク色に調整 |
| ローディングオーバーレイ | `rgba(15,23,42,0.8)` |
| バッジ（Success） | 背景 `rgba(22,163,74,0.2)`、テキスト `#4ade80` |
| バッジ（Warning） | 背景 `rgba(245,158,11,0.2)`、テキスト `#fbbf24` |
| バッジ（Danger） | 背景 `rgba(220,38,38,0.2)`、テキスト `#f87171` |
| KPI値 | テキスト色を `#60a5fa` (Blue 400) に変更 |

## 5. 計算ロジック

### 5.1 計算エンジン概要

本システムには2系統の計算パスが存在する。

**PricingEngine クラス** (`app/core/pricing.py`)
- フル機能のOOP計算エンジン。`calculate()` メソッドが市場価格分析、残価計算、リース料構造化、判定まで一括実行する。
- `calculate_simulation()` async関数（同ファイル末尾）がAPIレイヤーからの呼び出しをこのエンジンに委譲する。Supabaseから市場比較データを取得し、`PricingEngine.calculate()` に渡す。

**ラッパー関数群** (`app/core/pricing.py` 末尾)
- `_max_purchase_price()`, `_residual_value()`, `_monthly_lease_fee()`, `_assessment()`, `_build_schedule()` の5関数。
- HTMXフォームから呼ばれる `calculate_simulation_quick()` が直接使用するレガシーAPI。PricingEngineとは独立した簡易計算ロジック。

**calculate_simulation_quick** (`app/api/simulation.py` L628)
- `POST /api/v1/simulations/calculate` エンドポイント。HTMXからのフォームデータを受け取り、HTMLフラグメントを返す。
- 認証不要。ラッパー関数群（`_max_purchase_price`, `_monthly_lease_fee`, `_assessment`）と `ResidualValueCalculator` を直接使用する。
- 結果にはKPIカード、Chart.jsグラフ（バリュートランスファー、NAV比率、月次損益）、月次スケジュールテーブルを含む。

---

### 5.2 買取上限価格

#### PricingEngine.calculate_max_purchase_price

```
max_price = base_market_price × condition_factor × trend_factor × (1 - safety_margin_rate)
```

**base_market_price の算出:**

```python
deviation = |auction_median - retail_median| / ((auction_median + retail_median) / 2)

if deviation > acceptable_deviation_threshold (default 0.15):
    w = elevated_auction_weight  # default 0.85
else:
    w = auction_weight  # default 0.70

base_market_price = w × auction_median + (1 - w) × retail_median
```

**trend_factor の算出:**

```python
raw_factor = median(recent_prices) / median(baseline_prices)
trend_factor = clamp(raw_factor, trend_floor=0.80, trend_ceiling=1.20)
```

**safety_margin_rate の算出:**

```python
cv = std(prices) / mean(prices)   # 変動係数
dynamic = base_safety_margin(0.05) + cv × volatility_premium(1.5)
safety_margin = clamp(dynamic, min_safety_margin=0.03, max_safety_margin=0.20)
```

カテゴリ別デフォルト安全マージン:

| カテゴリ | マージン |
|---|---|
| SMALL | 0.05 |
| MEDIUM | 0.05 |
| LARGE | 0.07 |
| TRAILER_HEAD | 0.08 |
| TRAILER_CHASSIS | 0.06 |

#### ラッパー関数 `_max_purchase_price` (calculate_simulation_quick で使用)

```python
anchor = max(book_value, market_median)
max_price = int(anchor × 1.10) + body_option_value
```

`calculate_simulation_quick` では推奨買取価格をさらに5%引く:

```python
recommended_price = int(max_price × 0.95)
```

---

### 5.3 残価計算

#### ResidualValueCalculator.predict() (`app/core/residual_value.py`)

`calculate_simulation_quick` から呼ばれる残価計算の全体フロー:

**Step 1: 中古車耐用年数（簡便法）**

```python
remaining = legal_life - elapsed_years
if remaining > 0:
    useful_life = max(remaining, 2)
else:
    useful_life = max(int(elapsed_years × 0.2), 2)
```

法定耐用年数テーブル (`LEGAL_USEFUL_LIFE`):

| カテゴリ | 年数 |
|---|---|
| 普通貨物 | 5 |
| ダンプ | 4 |
| 小型貨物 | 3 |
| 特種自動車 | 4 |
| 被けん引車 | 4 |

**Step 2: 残存価額**

```python
salvage_value = max(purchase_price × 0.10, 1.0)
```

**Step 3: 定額法 (Straight-line)**

```python
annual_depreciation = (purchase_price - salvage_value) / legal_life
value = purchase_price - annual_depreciation × elapsed_years
sl_value = max(value, salvage_value)
```

**Step 4: 200%定率法 (Declining-balance)**

```python
rate = 2.0 / useful_life   # 200%DB率
guarantee_amount = purchase_price × (1.0 / useful_life × 0.9)

# 毎年の償却:
depreciation = value × rate

# depreciation < guarantee_amount になった時点で定額法に切替:
sl_depreciation = remaining_value / remaining_years

# 最低値 = 1.0（備忘価額）
```

**Step 5: シャーシ理論値**

```python
chassis_value = (sl_value + db_value) / 2.0
```

**Step 6: ボディ減価**

```python
body_ratio = 0.30          # ボディは購入価格の30%
chassis_ratio = 0.70

body_value = purchase_price × body_ratio × (body_retention ^ (elapsed_years / legal_life))
chassis_component = chassis_value × chassis_ratio / (chassis_ratio + body_ratio)

theoretical_value = chassis_component + body_value
```

BODY_RETENTION テーブル (`_BODY_RETENTION`):

| ボディタイプ | 残存率係数 |
|---|---|
| 平ボディ | 0.85 |
| バン | 0.90 |
| 冷凍冷蔵 | 0.75 |
| ウイング | 0.80 |
| ダンプ | 0.88 |
| タンク | 0.70 |
| クレーン | 0.65 |
| 塵芥車 | 0.60 |

**Step 7: 走行距離調整**

```python
expected_km = annual_mileage_norm × (elapsed_months / 12)
ratio = actual_mileage / expected_km
```

`_ANNUAL_MILEAGE_NORM` テーブル:

| カテゴリ | 年間走行距離(km) |
|---|---|
| 普通貨物 | 40,000 |
| ダンプ | 30,000 |
| 小型貨物 | 25,000 |
| 特種自動車 | 20,000 |
| 被けん引車 | 50,000 |

走行距離調整係数:

| ratio | 調整係数 |
|---|---|
| <= 0.5 | 1.10 |
| <= 0.8 | 1.05 |
| <= 1.0 | 1.00 |
| <= 1.3 | 0.93 |
| <= 1.5 | 0.85 |
| <= 2.0 | 0.75 |
| > 2.0 | 0.60 |

```python
theoretical_value = theoretical_value × mileage_adjustment
```

**Step 8: ハイブリッド予測（市場データがある場合）**

```python
market_weight = market_weight_base(0.6)

if sample_count < min_samples(3):
    market_weight = market_weight_base × (sample_count / min_samples)

market_weight = market_weight × max(0, 1.0 - volatility × volatility_penalty(0.5))

predicted = (1 - market_weight) × theoretical_value + market_weight × median_price
```

**Step 9: 万円単位に丸め**

```python
residual_value = round(predicted / 10000) × 10000
```

#### PricingEngine.calculate_residual_value（PricingEngine系統）

PricingEngine系統ではカテゴリ別の定数テーブルを使用:

| カテゴリ | 耐用年数 | 残存率 |
|---|---|---|
| SMALL | 7年 | 10% |
| MEDIUM | 9年 | 8% |
| LARGE | 10年 | 7% |
| TRAILER_HEAD | 10年 | 6% |
| TRAILER_CHASSIS | 12年 | 5% |

定額法:
```python
monthly_dep = (purchase_price - salvage_value) / (useful_life_years × 12)
chassis_value = max(purchase_price - monthly_dep × elapsed_months, salvage_value)
```

定率法:
```python
rate = 2.0 / useful_life_years
chassis_value = max(purchase_price × (1 - rate) ^ elapsed_years, salvage_value)
```

```python
residual = chassis_value × body_factor × mileage_adjustment
```

ボディ減価テーブル (`BODY_DEPRECIATION_TABLES`) は線形補間で参照。例: WING の場合 `(0, 1.00), (1, 0.92), (2, 0.85), ... (15, 0.22)`

走行距離調整 (PricingEngine版):
```python
expected_mileage = annual_standard × elapsed_years
deviation = (actual_mileage / expected_mileage) - 1.0

if deviation > 0:  # 過走行
    factor = 1.0 - deviation × over_mileage_penalty_rate(0.30)
else:              # 少走行
    factor = 1.0 + |deviation| × under_mileage_bonus_rate(0.15)

factor = clamp(factor, floor=0.70, ceiling=1.10)
```

年間標準走行距離 (PricingEngine版):

| カテゴリ | km/年 |
|---|---|
| SMALL | 30,000 |
| MEDIUM | 50,000 |
| LARGE | 80,000 |
| TRAILER_HEAD | 100,000 |

---

### 5.4 月額リース料

#### ラッパー関数 `_monthly_lease_fee` (calculate_simulation_quick で使用)

PMT方式:

```python
depreciable = purchase_price - residual_value
mr = target_yield_rate / 12   # 月利

# PMT公式
factor = (mr × (1 + mr)^n) / ((1 + mr)^n - 1)
base = int(depreciable × factor)

# 残価に対する金利コスト
residual_cost = int(residual_value × mr)

monthly_fee = base + residual_cost + insurance_monthly + maintenance_monthly
```

`calculate_simulation_quick` での呼び出しパラメータ:
- `insurance_monthly` = 15,000円
- `maintenance_monthly` = 10,000円
- `target_yield_rate` = フォーム入力値 / 100

#### PricingEngine.calculate_monthly_lease_payment

コスト積み上げ方式:

```python
# 元本回収（定額）
principal_recovery = (purchase_price - residual_value) / lease_term_months

# 金利（平均残高方式）
annual_rate = fund_cost_rate(0.020) + credit_spread(0.015) + liquidity_premium(0.005)  # = 0.040
average_balance = (purchase_price + residual_value) / 2
interest_charge = average_balance × annual_rate / 12

# 管理費
management_fee = purchase_price × monthly_management_fee_rate(0.002) + fixed_monthly_admin_cost(5,000)

# 利益マージン
subtotal = principal_recovery + interest_charge + management_fee
profit_margin = subtotal × profit_margin_rate(0.08)

total = subtotal + profit_margin
```

#### PricingEngine.calculate_from_target_yield（PMT公式）

```python
r = target_yield / 12
PV_residual = residual_value / (1 + r)^n
net = purchase_price - PV_residual
PMT = net × r / (1 - (1 + r)^(-n))
```

---

### 5.5 判定ロジック

#### ラッパー関数 `_assessment` (calculate_simulation_quick で使用)

```python
if effective_yield >= target_yield AND |market_deviation| <= 0.05:
    return "推奨"
if effective_yield < target_yield × 0.5 OR |market_deviation| > 0.10:
    return "非推奨"
return "要検討"
```

**effective_yield の算出** (`calculate_simulation_quick` 内):

```python
total_fee = monthly_fee × lease_term_months
effective_yield = ((total_fee + residual - recommended_price) / recommended_price) × (12 / lease_term_months)
```

**market_deviation の算出** (`calculate_simulation_quick` 内):

Supabaseクエリ:
```python
client.table("vehicles")
    .select("price_yen")
    .eq("is_active", True)
    .eq("maker", maker)        # maker指定時
    .eq("body_type", body_type) # body_type指定時
    .limit(50)
```

```python
market_median = median(prices)
market_deviation = |recommended_price - market_median| / market_median
```

#### PricingEngine.determine_assessment

```python
breakeven_ratio = breakeven_month / lease_term

# 非推奨条件（いずれか）:
- effective_yield < 0.02 (2%)
- breakeven_month が None（到達不能）
- breakeven_ratio > 0.90

# 推奨条件（すべて）:
- effective_yield >= 0.05 (5%)
- breakeven_ratio <= 0.70

# その他: 要検討
```

---

### 5.6 月次スケジュール

#### calculate_simulation_quick での計算

```python
dep_per_month = (recommended_price - residual) / lease_term_months

# 各月 m (1..n):
asset_value = max(recommended_price - dep_per_month × m, residual)
cumulative_income += monthly_fee

prev_asset = recommended_price - dep_per_month × (m - 1)
dep_expense = prev_asset - asset_value
fin_cost = int(prev_asset × (target_yield_rate / 100 / 12))
net_income = monthly_fee - 15000 - 10000   # 保険料・メンテ費控除
profit = net_income - dep_expense - fin_cost
cumulative_profit += profit

net_fund_value = asset_value + cumulative_income
nav_ratio = net_fund_value / recommended_price
```

#### PricingEngine.calculate_monthly_schedule

```python
total_dep = purchase_price - salvage_value
total_months = useful_life_years × 12
dep_expense = total_dep / total_months   # 月額（耐用年数ベース）

asset_value = max(purchase_price - dep_expense × m, salvage_value)

# 金融コスト（逓減残高方式）
annual_rate = fund_cost_rate + credit_spread + liquidity_premium  # = 0.040
financing_cost = remaining_balance × (annual_rate / 12)

monthly_profit = lease_income - dep_expense - financing_cost
cumulative_profit += monthly_profit

# 中途解約損失推定
forced_sale_value = asset_value × forced_sale_discount(0.85)
remaining_payments = min(penalty_months(3), lease_term - m) × monthly_payment
termination_loss = forced_sale_value + cumulative_income - purchase_price - remaining_payments

# 残高更新
remaining_balance -= (lease_income - financing_cost)
remaining_balance = max(remaining_balance, 0)
```

損益分岐点:
```python
# 月 m で breakeven:
cumulative_income(m) >= purchase_price - asset_value(m)
```

---

### 5.7 バリュートランスファー分析

`calculate_simulation_quick` の結果HTMLで可視化されるNAV（Net Asset Value）の計算:

```python
# 各月のNAV = 物理資産価値 + 累積キャッシュ回収
net_fund_value = asset_value + cumulative_income

# NAV比率 = NAV / 初期投資額
nav_ratio = net_fund_value / recommended_price
```

Chart.jsで3つのチャートを生成:
1. **バリュートランスファーチャート**: asset_value (減少曲線) vs cumulative_income (増加曲線) の推移
2. **NAV比率チャート**: `nav_ratio × 100` の推移と60%安全ライン (`[60] × lease_term_months`)
3. **月次損益チャート**: monthly_profit (棒グラフ) + cumulative_profit (折れ線オーバーレイ)

60%安全ラインの意味: NAV比率が60%を下回ると、中途解約時に投資元本を大きく毀損するリスクがある閾値。

---

### 5.8 自動保存ロジック

`calculate_simulation_quick` 内での自動保存フロー:

**Step 1: JWT認証確認**

```python
access_token = request.cookies.get("access_token")
```

トークンが存在しない場合は保存をスキップし、代わりに手動保存フォームを表示する。

**Step 2: JWTデコード**

```python
header = jwt.get_unverified_header(access_token)

if header["alg"] == "ES256":
    # Supabase JWKSを使用
    jwks = _get_jwks(settings.supabase_url)
    payload = jwt.decode(access_token, jwks, algorithms=["ES256"], audience="authenticated")
else:
    # HS256 (JWT secret直接検証)
    payload = jwt.decode(access_token, settings.supabase_jwt_secret, algorithms=["HS256"], options={"verify_aud": False})

user_id = payload["sub"]
```

**Step 3: Supabaseへinsert**

```python
save_data = {
    "user_id": user_id,
    "title": f"{maker} {model} シミュレーション",
    "target_model_name": f"{maker} {model}",
    "target_model_year": year_val,
    "target_mileage_km": mileage_km,
    "purchase_price_yen": recommended_price,
    "market_price_yen": acquisition_price,
    "lease_monthly_yen": monthly_fee,
    "lease_term_months": lease_term_months,
    "total_lease_revenue_yen": total_fee,
    "expected_yield_rate": round(effective_yield, 4),
    "status": "completed",
    "result_summary_json": {
        "maker", "model", "body_type", "vehicle_class",
        "max_price", "residual_value", "residual_rate",
        "assessment", "breakeven_months",
        "target_yield_rate", "actual_yield_rate", "equipment"
    }
}

client.table("simulations").insert(save_data).execute()
saved_sim_id = result.data[0]["id"]
```

保存成功時: `自動保存済み` バッジ + 保存結果確認リンク (`/simulation/{id}/result`) を表示。

保存失敗時: 例外を握りつぶし (`pass`)、計算結果の表示には影響しない。手動保存ボタンは表示されない（トークンが存在するため）。

未認証時: `hx-post="/api/v1/simulations/save"` の手動保存フォームをHTMLに埋め込む。

## 6. APIエンドポイント一覧

### 6.1 認証API (`/auth/*`)

ルーター定義: `app/api/auth.py`  
プレフィックス: `/auth`

| HTTPメソッド | パス | 認証 | 概要 | リクエスト | レスポンス |
|---|---|---|---|---|---|
| POST | `/auth/login` | 不要 | メール/パスワードでログイン。成功時にHttpOnlyクッキーにJWTを設定し `/dashboard` へリダイレクト。HTMX対応 | Form: `email`, `password` | 302リダイレクト or HTMX `HX-Redirect` / エラー時HTMLフラグメント |
| POST | `/auth/logout` | 不要 | ログアウト。認証クッキーを削除し、Supabaseセッションを無効化（ベストエフォート） | なし | 302リダイレクト (`/login`) or HTMX `HX-Redirect` |
| GET | `/auth/me` | 必要 (`get_current_user`) | 現在ログイン中のユーザー情報を取得 | なし | `{ id, email, role }` |
| POST | `/auth/refresh` | Cookie (`refresh_token`) | リフレッシュトークンで新しいアクセストークンを発行。新JWTペアをクッキーに書き込み | Cookie: `refresh_token` | `{ status: "ok" }` / 401エラー |
| GET | `/auth/forgot-password` | 不要 | パスワードリセットページを表示 | なし | HTML (`pages/forgot_password.html`) |
| POST | `/auth/forgot-password` | 不要 | パスワードリセットメールを送信（存在しないメールでも同一レスポンス） | Form: `email` | HTMLフラグメント（成功/エラーメッセージ） |

---

### 6.2 シミュレーションAPI (`/api/v1/simulations/*`)

ルーター定義: `app/api/simulation.py`  
プレフィックス: `/api/v1/simulations`

| HTTPメソッド | パス | 認証 | 概要 | リクエスト | レスポンス |
|---|---|---|---|---|---|
| POST | `/api/v1/simulations` | 必要 (`get_current_user`) | リースバック査定シミュレーションを実行し、結果をDBに保存。HTMX時はHTMLフラグメント返却 | JSON: `SimulationInput` (maker, model, year, mileage, vehicle_class, body_type, acquisition_price, book_value, target_yield_rate, lease_term_months 等) | 201: `SuccessResponse { data: SimulationResponse }` / HTMX: HTMLフラグメント |
| GET | `/api/v1/simulations` | 必要 (`get_current_user`) | 自分のシミュレーション履歴をページネーション付きで取得 | Query: `page`, `per_page`, `sort`, `order`, `date_from`, `date_to` | `PaginatedResponse { data: [...], meta: PaginationMeta }` / HTMX: HTML表フラグメント |
| GET | `/api/v1/simulations/{simulation_id}` | 必要 (本人 or admin) | シミュレーション詳細を取得 | Path: `simulation_id` | `SuccessResponse { data: SimulationResponse }` / HTMX: HTMLフラグメント |
| DELETE | `/api/v1/simulations/{simulation_id}` | 必要 (本人のみ) | draftステータスのシミュレーションを削除 | Path: `simulation_id` | `SuccessResponse { data: { deleted: true, id } }` |
| POST | `/api/v1/simulations/compare` | 必要 (本人 or admin) | 2件のシミュレーションを比較し差分を算出 | JSON: `CompareRequest { simulation_ids: [id1, id2] }` | `SuccessResponse { data: CompareResponse { simulations, diff } }` |
| POST | `/api/v1/simulations/calculate` | 不要 | フォームデータから簡易計算（認証時は自動保存）。Chart.js付きHTMLフラグメントを返却 | Form: `maker`, `model`, `mileage_km`, `acquisition_price`, `book_value`, `body_type`, `body_option_value`, `target_yield_rate`, `lease_term_months`, `registration_year_month`, `vehicle_class`, `equipment[]` 等 | HTMLフラグメント（KPIカード、チャート、月別スケジュール表） |
| POST | `/api/v1/simulations/calculate-form` | 必要 (`get_current_user`) | HTMLフォームからの簡易計算（保存なし）。HTMXスワップ用HTMLフラグメントを返却 | Form: `maker`, `model`, `year`, `mileage`, `vehicle_class`, `body_type`, `acquisition_price`, `book_value`, `target_yield_rate`, `lease_term_months`, `residual_rate`, `insurance_monthly`, `maintenance_monthly` 等 | HTMLフラグメント |
| POST | `/api/v1/simulations/save` | Cookie認証 (手動検証) | 計算結果をDBに保存（HTMX用、calculate後の明示的保存） | Form: `maker`, `model`, `registration_year_month`, `mileage_km`, `recommended_price`, `max_price`, `monthly_fee`, `total_fee`, `effective_yield`, `residual`, `residual_rate`, `assessment`, `breakeven`, `vehicle_class`, `equipment[]` 等 | HTMLフラグメント（成功バッジ or エラーメッセージ） |

---

### 6.3 相場データAPI (`/api/v1/market-prices/*`)

ルーター定義: `app/api/market_prices.py`  
プレフィックス: `/api/v1/market-prices`

| HTTPメソッド | パス | 認証 | 概要 | リクエスト | レスポンス |
|---|---|---|---|---|---|
| GET | `/api/v1/market-prices/` | 不要 | 相場データの検索・一覧取得（ページネーション・統計付き）。HTMX時はHTML表フラグメント | Query: `maker`, `model`, `year_from`, `year_to`, `mileage_from`, `mileage_to`, `body_type`, `price_from`, `price_to`, `page`, `per_page`, `sort`, `order` | `{ status, data: [...], meta: PaginationMeta, stats: { count, avg, median, min, max, std } }` / HTMX: HTML |
| GET | `/api/v1/market-prices/statistics` | 不要 | 条件に合致する車両の統計サマリーを取得 | Query: `maker`, `model`, `year`, `body_type` | `SuccessResponse { data: { count, avg, median, min, max, std } }` |
| GET | `/api/v1/market-prices/export` | 不要 | 条件に合致する車両データをCSVエクスポート | Query: `maker`, `model`, `year_from`, `year_to`, `mileage_from`, `mileage_to`, `body_type`, `price_from`, `price_to`, `sort`, `order` | `StreamingResponse` (CSV file: `market_prices_YYYYMMDD_HHMMSS.csv`) |
| POST | `/api/v1/market-prices/import` | 必要 (admin / service_role) | CSVファイルから車両レコードを一括インポート（source_idでupsert） | Multipart: `file` (CSV) | `SuccessResponse { data: { success_count, error_count, errors } }` |
| GET | `/api/v1/market-prices/{vehicle_id}` | 不要 | 車両レコード1件の詳細を取得。HTMX時はHTMLフラグメント | Path: `vehicle_id` (UUID) | `SuccessResponse { data: vehicle }` / HTMX: HTML |
| POST | `/api/v1/market-prices/` | 必要 (admin / service_role) | 車両レコードを手動作成 | JSON: `VehicleCreate` (source_site, source_url, source_id, maker, model_name, body_type, model_year, mileage_km, price_yen 等) | 201: `SuccessResponse { data: vehicle }` |
| PUT | `/api/v1/market-prices/{vehicle_id}` | 必要 (admin / service_role) | 車両レコードを更新 | Path: `vehicle_id` (UUID), JSON: `VehicleCreate` | `SuccessResponse { data: vehicle }` |
| DELETE | `/api/v1/market-prices/{vehicle_id}` | 必要 (admin / service_role) | 車両レコードを論理削除 (`is_active=False`) | Path: `vehicle_id` (UUID) | `SuccessResponse { data: { id, deleted: true } }` |

---

### 6.4 マスタAPI (`/api/v1/masters/*`)

ルーター定義: `app/api/masters.py`  
プレフィックス: `/api/v1/masters`

| HTTPメソッド | パス | 認証 | 概要 | リクエスト | レスポンス |
|---|---|---|---|---|---|
| GET | `/api/v1/masters/makers` | 必要 (`get_current_user`) | メーカー一覧を取得。HTMX時は`<option>`タグのHTMLを返却 | なし | `{ status: "success", data: MakerResponse[] }` / HTMX: HTML `<option>` |
| POST | `/api/v1/masters/makers` | 必要 (admin) | メーカーを新規作成 | JSON: `MakerCreate` (name 等) | 201: `{ status: "success", data: MakerResponse }` |
| GET | `/api/v1/masters/makers/{maker_id}/models` | 必要 (`get_current_user`) | 指定メーカーに属するモデル一覧を取得。HTMX時は`<option>`タグのHTMLを返却 | Path: `maker_id` (UUID) | `{ status: "success", data: ModelResponse[] }` / HTMX: HTML `<option>` |
| POST | `/api/v1/masters/makers/{maker_id}/models` | 必要 (admin) | 指定メーカー配下にモデルを新規作成 | Path: `maker_id` (UUID), JSON: `ModelCreate` (name 等) | 201: `{ status: "success", data: ModelResponse }` |
| GET | `/api/v1/masters/body-types` | 必要 (`get_current_user`) | ボディタイプ一覧を取得。HTMX時は`<option>`タグのHTMLを返却 | なし | `{ status: "success", data: BodyTypeResponse[] }` / HTMX: HTML `<option>` |
| POST | `/api/v1/masters/body-types` | 必要 (admin) | ボディタイプを新規作成 | JSON: `BodyTypeCreate` | 201: `{ status: "success", data: BodyTypeResponse }` |
| PUT | `/api/v1/masters/body-types/{body_type_id}` | 必要 (admin) | ボディタイプを更新 | Path: `body_type_id` (UUID), JSON: `BodyTypeUpdate` | `{ status: "success", data: BodyTypeResponse }` |
| DELETE | `/api/v1/masters/body-types/{body_type_id}` | 必要 (admin) | ボディタイプを論理削除 (`is_active=False`) | Path: `body_type_id` (UUID) | `{ status: "success", data: ..., message: "Body type deactivated" }` |
| GET | `/api/v1/masters/categories` | 必要 (`get_current_user`) | 車両カテゴリ一覧を取得 | なし | `{ status: "success", data: VehicleCategoryResponse[] }` |
| GET | `/api/v1/masters/depreciation-curves` | 必要 (`get_current_user`) | 減価償却カーブ一覧を取得（カテゴリIDでフィルター可） | Query: `category_id` (UUID, optional) | `{ status: "success", data: DepreciationCurveResponse[] }` |
| GET | `/api/v1/masters/models-by-maker` | 不要 | メーカー名からモデル名の`<option>`リストをHTMLで返却（HTMX用） | Query: `maker_name` | HTML `<option>` 要素 |
| POST | `/api/v1/masters/depreciation-curves` | 必要 (admin) | 減価償却カーブポイントを作成/更新（category_id + yearでupsert） | JSON: `DepreciationCurveCreate` (category_id, year, rate 等) | 201: `{ status: "success", data: DepreciationCurveResponse }` |

---

### 6.5 ダッシュボードAPI (`/api/v1/dashboard/*`)

ルーター定義: `app/api/dashboard.py`  
プレフィックス: `/api/v1/dashboard`

| HTTPメソッド | パス | 認証 | 概要 | リクエスト | レスポンス |
|---|---|---|---|---|---|
| GET | `/api/v1/dashboard/kpi` | 不要 | ダッシュボード用KPIデータをHTMLフラグメントで返却（今月査定数、平均利回り、市場データ数） | なし | HTML（KPIカード3枚: 今月査定数、平均利回り、市場データ数）。エラー時は `--` 表示のフォールバックHTML |

---

### 6.6 ページルート (HTML)

ルーター定義: `app/api/pages.py`  
プレフィックス: なし（ルート直下）

| HTTPメソッド | パス | 認証 | 概要 | リクエスト | レスポンス |
|---|---|---|---|---|---|
| GET | `/` | 不要 | `/dashboard` へ302リダイレクト | なし | 302リダイレクト |
| GET | `/login` | 不要 | ログインページを表示 | なし | HTML (`pages/login.html`) |
| GET | `/dashboard` | 必要 (Cookie) | ダッシュボードページ。KPI（査定数、平均利回り、市場データ数）と直近5件のシミュレーション履歴を表示 | なし | HTML (`pages/dashboard.html`) |
| GET | `/simulation/new` | 必要 (Cookie) | シミュレーション新規作成フォーム。メーカー、ボディタイプ、カテゴリ、モデル、装備オプションのマスタデータをプリロード | なし | HTML (`pages/simulation.html`) |
| GET | `/simulation/{simulation_id}/result` | 必要 (Cookie) | シミュレーション結果詳細ページ。Chart.jsチャートデータ（資産推移、NAV比率、月次損益）を含む | Path: `simulation_id` | HTML (`pages/simulation_result.html`) |
| GET | `/simulations` | 必要 (Cookie) | シミュレーション一覧ページ（直近50件） | なし | HTML (`pages/simulation_list.html`) |
| GET | `/market-data` | 必要 (Cookie) | 相場データ一覧ページ（ページネーション・フィルター付き）。統計サマリー（平均価格、中央値）を含む | Query: `page` | HTML (`pages/market_data_list.html`) |
| GET | `/market-data/table` | 不要 | 相場データテーブルのHTMLフラグメント（HTMX用）。フィルター・ページネーション対応 | Query: `maker`, `body_type`, `year_from`, `year_to`, `price_from`, `price_to`, `keyword`, `page`, `per_page` | HTML (`partials/market_prices_table.html`) |
| GET | `/market-data/{item_id}` | 必要 (Cookie) | 相場データ詳細ページ。類似車両（同メーカー/ボディタイプ）5件を併せて表示 | Path: `item_id` | HTML (`pages/market_data_detail.html`) |

**備考:**
- ページルートの認証は `_get_optional_user()` によるCookieベースの任意認証。未認証時は `/login` へリダイレクト
- HTMX対応エンドポイントは `HX-Request` ヘッダーの有無でJSON/HTMLを出し分ける
- 管理系操作（作成・更新・削除）は `require_role(["admin"])` または `require_role(["admin", "service_role"])` による権限チェックあり

## 7. ビジュアライゼーション

本システムでは **Chart.js v4**（CDN: `chart.js@4/dist/chart.umd.min.js`）を使用し、シミュレーション結果を3種類のチャートで可視化している。チャートは2つの異なるコンテキスト（リアルタイム計算結果・保存済み結果ページ）で描画され、さらに汎用パーシャルテンプレートおよびHTMXスワップ対応の初期化機構が存在する。

### 7.1 シミュレーション結果のチャート（リアルタイム計算）

`app/api/simulation.py` の `calculate` エンドポイントが返すHTML内にインラインで `<script>` タグとして埋め込まれる。月次スケジュールデータをPython側で `json.dumps()` しJavaScriptに注入する方式。

#### データ準備（Python側、simulation.py 行850-858）

```python
months_labels = json.dumps([f"{s['month']}月" for s in schedule])
asset_values = json.dumps([s["asset_value"] for s in schedule])
cumulative_incomes = json.dumps([s["cumulative_income"] for s in schedule])
monthly_profits = json.dumps([s["monthly_profit"] for s in schedule])
cumulative_profits = json.dumps([s["cumulative_profit"] for s in schedule])
nav_ratios = json.dumps([s["nav_ratio"] * 100 for s in schedule])
nav_60_line = json.dumps([60] * lease_term_months)
```

#### 共通ユーティリティ

- **円フォーマッタ**: `yenFormatter` - 値を万円単位に変換（`¥{v/10000}万`）
- **コンテナ**: `.chart-wrap` クラス（`position: relative; height: 350px`、768px以下で250px）

#### 7.1.1 バリュートランスファー分析チャート

| 項目 | 値 |
|---|---|
| **Canvas ID** | `chart-value-transfer` |
| **チャートタイプ** | `line` |
| **データセット数** | 2 |

**データセット詳細:**

| # | label | データソース | borderColor | backgroundColor | fill | tension |
|---|---|---|---|---|---|---|
| 1 | `資産簿価` | `asset_values`（月次減価償却後の簿価） | `#6366f1`（Indigo） | `rgba(99,102,241,0.1)` | `true` | `0.3` |
| 2 | `累積リース収入` | `cumulative_incomes`（月額リース料の累積和） | `#10b981`（Emerald） | `rgba(16,185,129,0.1)` | `true` | `0.3` |

**オプション:**
- `responsive: true`, `maintainAspectRatio: false`
- Y軸: `yenFormatter`（万円単位表示）
- 凡例: 上部表示（`position: 'top'`）

**分析意図:** 資産簿価の逓減と累積リース収入の逓増が交差する点がバリュートランスファーのクロスオーバーポイントとなり、投資回収の視覚的な理解を提供する。

#### 7.1.2 NAV推移チャート

| 項目 | 値 |
|---|---|
| **Canvas ID** | `chart-nav` |
| **チャートタイプ** | `line` |
| **データセット数** | 2 |

**データセット詳細:**

| # | label | データソース | borderColor | スタイル |
|---|---|---|---|---|
| 1 | `NAV比率 (%)` | `nav_ratios`（`nav_ratio * 100`） | `#2563eb`（Blue） | `fill: true`, `tension: 0.3`, `backgroundColor: rgba(37,99,235,0.1)` |
| 2 | `60%ライン（安全基準）` | `nav_60_line`（全月 `60` 固定） | `#f59e0b`（Amber） | `borderDash: [8, 4]`, `borderWidth: 2`, `pointRadius: 0`, `fill: false` |

**オプション:**
- Y軸: `min: 0`, `max: 200`, ティック表示 `v + '%'`
- 凡例: 上部表示

**安全閾値の可視化:** 60%ラインは破線で描画され、NAV比率がこの閾値を下回ると元本毀損リスクが高いことを示す。NAV = (資産簿価 + 累積リース収入) / 買取価格 で算出。

#### 7.1.3 月次損益推移チャート

| 項目 | 値 |
|---|---|
| **Canvas ID** | `chart-pnl` |
| **チャートタイプ** | `bar`（複合チャート） |
| **データセット数** | 2 |

**データセット詳細:**

| # | label | type | データソース | 色 | 軸 |
|---|---|---|---|---|---|
| 1 | `月次損益` | `bar` | `monthly_profits` | 動的: 黒字 `rgba(16,185,129,0.7)`（緑）/ 赤字 `rgba(239,68,68,0.7)`（赤） | デフォルトY軸 |
| 2 | `累積損益` | `line` | `cumulative_profits` | `borderColor: '#2563eb'`（Blue） | `y1`（右軸） |

**オプション:**
- バー: `borderRadius: 3`
- 左Y軸（`y`）: `yenFormatter`（万円単位）
- 右Y軸（`y1`）: `yenFormatter`、`position: 'right'`, `grid: { display: false }`
- 凡例: 上部表示

**描画ロジック:** 月次損益バーの色は `monthlyProfits.map()` で動的に決定される。正値はEmerald系の緑、負値はRed系の赤で着色。

### 7.2 保存済みシミュレーション結果のチャート

`app/templates/pages/simulation_result.html` にて、保存済みの `simulation.result_summary_json` からチャートデータを復元して描画する。テンプレート変数 `chart_data` が存在する場合のみチャートセクションが表示される（`{% if chart_data %}`）。

#### データ注入方式

```javascript
var months = {{ chart_data.months | safe }};
var assetValues = {{ chart_data.asset_values | safe }};
var cumulativeIncomes = {{ chart_data.cumulative_incomes | safe }};
var navRatios = {{ chart_data.nav_ratios | safe }};
var nav60 = {{ chart_data.nav_60_line | safe }};
var monthlyProfits = {{ chart_data.monthly_profits | safe }};    // 条件付き
var cumulativeProfits = {{ chart_data.cumulative_profits | safe }}; // 条件付き
```

#### チャート構成（3種）

リアルタイム版と同一の3チャートを描画するが、以下の差異がある:

| チャート | Canvas ID | コンテナ高さ | 差異 |
|---|---|---|---|
| バリュートランスファー | `chart-vt` | `350px` | IDが異なる（`chart-value-transfer` → `chart-vt`） |
| NAV推移 | `chart-nav` | `300px` | 高さがやや低い（350px → 300px） |
| 月次損益推移 | `chart-pnl` | `300px` | `chart_data.monthly_profits` が定義されている場合のみ描画 |

**Chart.js読み込み待機:** `initCharts` 関数内で `typeof Chart === 'undefined'` をチェックし、未ロード時は `setTimeout(initCharts, 200)` で再試行するポーリング方式を採用。

### 7.3 汎用チャートパーシャル

`app/templates/partials/chart_fragment.html` は再利用可能な単一データセットチャートコンポーネント。

#### テンプレート変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `chart_id` | `mainChart` | Canvas要素のID |
| `labels` | (必須) | X軸ラベル配列 |
| `values` | (必須) | データ値配列 |
| `chart_type` | `line` | チャートタイプ（`line` / `bar`） |
| `chart_label` | `データ` | データセットラベル |

#### 特徴
- `data-*` 属性にJSONを保持し、`canvas` 要素自体がデータストアを兼ねる
- `window._chartInstances` オブジェクトでインスタンスを管理し、再描画時に既存インスタンスを `destroy()` してメモリリークを防止
- 色: `rgba(59,130,246,1)` / `rgba(59,130,246,0.1)`（Blue系統一色）
- Y軸: `¥` + `toLocaleString()` 形式（万円単位ではなく円単位）

### 7.4 HTMXフラグメント内チャート

`app/templates/partials/simulation_result_fragment.html` はHTMXスワップで挿入される結果フラグメント用のチャート。

#### スケジュールチャート

| 項目 | 値 |
|---|---|
| **Canvas ID** | `scheduleChart` |
| **チャートタイプ** | `bar`（複合） |
| **データセット数** | 3 |

**データセット詳細:**

| # | label | type | データソース | 色 | 軸 | order |
|---|---|---|---|---|---|---|
| 1 | `リース収入` | `bar` | `data-income` | `rgba(59,130,246,0.6)`（Blue） | デフォルト（`y`） | 2 |
| 2 | `月次損益` | `bar` | `data-profit` | 動的: 正 `rgba(34,197,94,0.6)` / 負 `rgba(239,68,68,0.6)` | デフォルト（`y`） | 3 |
| 3 | `簿価残高` | `line` | `data-asset` | `rgba(234,179,8,1)`（Yellow） | `y1`（右軸） | 1 |

**オプション:**
- デュアルY軸: 左 `金額 (円)` / 右 `簿価 (円)`
- `interaction: { mode: 'index', intersect: false }`（ホバー時に全データセットのツールチップ表示）
- 右軸のグリッド線は非表示（`grid: { drawOnChartArea: false }`）

### 7.5 Chart.js初期化・ライフサイクル管理

`static/js/app.js` でグローバルなChart.jsライフサイクル管理を実装。

#### HTMX連携

```javascript
// スワップ前に既存チャートを破棄
document.body.addEventListener('htmx:beforeSwap', function(event) {
    destroyCharts(event.detail.target);
});

// スワップ完了後に新規チャートを初期化
document.body.addEventListener('htmx:afterSettle', function(event) {
    initCharts(event.detail.target);
});
```

#### 汎用初期化関数 `initCharts(container)`

- `canvas[data-chart]` 属性を持つ要素を検索
- `data-chart` 属性のJSON文字列をパースし、Chart.jsコンフィグとして使用
- `canvas._chartInstance` でインスタンスを保持、重複初期化を防止

#### 汎用破棄関数 `destroyCharts(container)`

- コンテナ内の全 `canvas[data-chart]` を走査
- `_chartInstance.destroy()` を呼び出し、参照を `null` に設定

### 7.6 Chart.js共通設定サマリー

| 設定項目 | リアルタイム計算 | 保存済み結果 | フラグメント |
|---|---|---|---|
| **Chart.jsバージョン** | v4 (CDN) | v4 (CDN) | v4（グローバル読込依存） |
| **responsive** | `true` | `true` | `true` |
| **maintainAspectRatio** | `false` | `false` | `false`（汎用パーシャルのみ`false`） |
| **Y軸フォーマット** | `¥{万}万` | `¥{万}万` | `¥ + toLocaleString()` |
| **凡例** | `top` | `top` | `top` |
| **インスタンス管理** | IIFE（即時関数） | IIFE + `initCharts`ポーリング | `window._scheduleChartInstance` / `window._chartInstances` |

### 7.7 ダッシュボード

`app/templates/pages/dashboard.html` にはチャートは含まれていない。KPIカードと最近のシミュレーション一覧テーブルのみで構成される。

## 8. スクレイピングシステム

### 8.1 アーキテクチャ

スクレイピングシステムは以下の4層構造で構成される。

```
BaseScraper (抽象基底クラス)
    ├── TruckKingdomScraper (truck-kingdom.com)
    └── SteerlinkScraper (steerlink.co.jp)
            ↓ raw dict[]
        VehicleParser (正規化・バリデーション)
            ↓ cleaned dict[]
        ScraperScheduler (オーケストレーション)
            ↓ upsert
        Supabase (vehicles / vehicle_price_history / scraping_logs)
```

**BaseScraper** (`scraper/base.py`) は Playwright (headless Chromium) を使った非同期スクレイパーの抽象クラス。サブクラスは以下の4メソッド/プロパティを実装する:

| メソッド | 役割 |
|---|---|
| `scrape_listing_page(page, url)` | 一覧ページから車両カードを抽出 |
| `scrape_detail_page(page, url)` | 個別車両ページからスペック情報を抽出 |
| `get_listing_urls()` | クロール対象URLリストを生成 |
| `site_name` (property) | サイト識別子 (例: `"truck_kingdom"`) |

`run(mode)` メソッドで実行モードを制御する:
- `"full"`: 一覧ページ巡回 + 各車両の詳細ページ取得
- `"listing"`: 一覧ページのみ (詳細ページはスキップ)

レート制限は `delay_min`〜`delay_max` 秒のランダムスリープ (デフォルト3〜7秒)。リトライは最大3回、指数バックオフ (`2^attempt + random(0,1)` 秒) で行う。

### 8.2 対象サイト

| サイト | クラス | カテゴリ | 最大ページ数 |
|---|---|---|---|
| truck-kingdom.com (トラック王国) | `TruckKingdomScraper` | `large-truck`, `medium-truck`, `small-truck`, `trailer` | 30 |
| steerlink.co.jp (ステアリンク) | `SteerlinkScraper` | `large`, `medium`, `small`, `trailer`, `tractor`, `bus` | 20 |

両スクレイパーとも複数のCSSセレクタ候補を優先度順に試行する「レジリエント・セレクタ戦略」を採用しており、サイトのHTML構造変更に対する耐性を持つ。例えば車両カードの検出には `.vehicle-card` → `.p-searchResultItem` → `.search-result-item` → ... と7パターンを順番に試す。

詳細ページではスペックテーブル (`<table>` の `th`/`td` ペア、および `<dl>` の `dt`/`dd` ペア) からキー・バリューを抽出し、日本語キー名 (「メーカー」「年式」「走行距離」等) をフィールド名にマッピングする。

### 8.3 取得項目

VehicleParser (`scraper/parsers/vehicle_parser.py`) が出力する正規化済みレコードの主要フィールド:

| フィールド | 型 | 説明 |
|---|---|---|
| `source_site` | str | スクレイピング元サイト識別子 |
| `source_url` | str | 元URL |
| `source_id` | str | サイト内の車両ID (URLから抽出) |
| `maker` | str | メーカー名 (正規化済み) |
| `model_name` | str | 車種名 (正規化済み) |
| `body_type` | str | 架装タイプ (正規化済み) |
| `model_year` | int | 年式 (西暦) |
| `mileage_km` | int | 走行距離 (km) |
| `price_yen` | int | 価格 (円) |
| `price_tax_included` | bool | 税込みかどうか |
| `tonnage_class` | str | トン数区分 (`小型`/`中型`/`大型`/`増トン`) |
| `location_prefecture` | str | 所在都道府県 |
| `image_url` | str | 車両画像URL |
| `scraped_at` | str (ISO) | スクレイピング日時 (UTC) |
| `listing_status` | str | リスティング状態 (`active`) |

追加のテキストフィールド: `color`, `engine_type`, `fuel_type`, `transmission`, `drive_type`, `equipment`, `description`, `chassis_number`, `model_number`, `inspection`

追加の数値フィールド: `horse_power`, `max_load_kg`, `vehicle_weight_kg`, `gross_vehicle_weight_kg`, `cab_width`, `wheelbase`, `length_cm`, `width_cm`, `height_cm`, `doors`, `seats`, `displacement_cc`, `fuel_economy`

### 8.4 データクレンジング

`scraper/utils.py` に定義された正規化関数群:

**文字列前処理:**
- `zenkaku_to_hankaku()`: 全角英数字・記号を半角に変換 (例: `１２３ＡＢＣ` → `123ABC`)
- `clean_text()`: 全角→半角変換 + 空白正規化 + strip

**価格正規化 (`normalize_price`):**
- `"450万円(税込)"` → `(4_500_000, True)`
- `"12,500,000円"` → `(12_500_000, False)`
- `"ASK"` / `"応談"` → `(None, False)`
- 税込み判定: テキスト中の「税込」「込み」等を検出

**走行距離正規化 (`normalize_mileage`):**
- `"18.5万km"` → `185_000`
- `"185,000km"` → `185_000`
- `"不明"` → `None`

**年式正規化 (`normalize_year`):**
- 和暦対応: `"R1"` → `2019`, `"H30"` → `2018`, `"S63"` → `1988`
- 和暦の表記バリエーション: `R`, `令和`, `令`, `H`, `平成`, `平`, `S`, `昭和`, `昭`
- 西暦: `"2019年"` → `2019`

**メーカー名正規化 (`normalize_maker`):**

マッピングテーブル (`MAKER_MAP`) で表記ゆれを吸収する。対応メーカーは16社:

| 正規名 | バリエーション例 |
|---|---|
| いすゞ | いすず, イスズ, ISUZU |
| 日野 | ヒノ, HINO |
| 三菱ふそう | 三菱, ミツビシ, フソウ, FUSO, MITSUBISHI |
| UDトラックス | UD, 日産ディーゼル, ニッサンディーゼル |
| トヨタ | TOYOTA |
| 日産 | ニッサン, NISSAN |
| メルセデス・ベンツ | ベンツ, メルセデス, BENZ, MERCEDES |
| ボルボ | VOLVO |
| スカニア | SCANIA |

**車種名正規化 (`normalize_model`):**

`MODEL_MAP` で主要車種をカタカナ表記に統一 (例: `FORWARD` → `フォワード`, `GIGA` → `ギガ`)。対応車種数: 約20車種 (ギガ, フォワード, エルフ, プロフィア, レンジャー, デュトロ, スーパーグレート, ファイター, キャンター, クオン, コンドル 等)。

**架装タイプ正規化 (`normalize_body_type`):**

`BODY_TYPE_MAP` で約50パターンの表記ゆれを約20カテゴリに集約:

| 正規名 | バリエーション例 |
|---|---|
| 平ボディ | 平ボディー, 平ボデー, 平, フラットボディ |
| ウイング | ウィング, ウイングボディ, ウィングボディ |
| ダンプ | ダンプカー, DUMP |
| 冷凍車 | 冷蔵冷凍車, 冷蔵車, 冷凍冷蔵車 |
| クレーン | クレーン付き, クレーン付, ユニック, UNIC |
| トラクタ | トラクター, トラクターヘッド, トレーラーヘッド, ヘッド |
| 塵芥車 | パッカー車, パッカー, ゴミ収集車 |
| 脱着ボディ | アームロール, フックロール, コンテナ専用車 |

部分一致の場合は最長一致が優先される。

正規化マッピングは `config/normalization/makers.yaml` および `config/normalization/body_types.yaml` にもYAML形式で定義されている (コード内の辞書と併存)。

**バリデーション (`is_valid_vehicle`):**
- 必須フィールド: `maker`, `model`, `year`, `price`
- 年式の有効範囲: 1980〜2030
- 価格の有効範囲: 1万円〜5億円
- 走行距離の有効範囲 (任意): 0〜500万km

**トン数自動分類 (`VehicleParser._classify_tonnage`):**
- 最大積載量から判定: 3t以下→小型、3〜8t→中型、8t超→大型
- GVW (車両総重量) からも判定: 5t以下→小型、5〜11t→中型、11t超→大型

### 8.5 バッチ実行

**GitHub Actions 自動実行** (`.github/workflows/scrape.yml`):
- スケジュール: 毎日 UTC 18:00 (JST 03:00)
- matrix戦略で `truck_kingdom` と `steerlink` を並列実行
- `fail-fast: false` により、一方のサイトが失敗しても他方は継続
- タイムアウト: 120分
- concurrencyグループ `scraping` で多重起動を防止 (ただしキャンセルはしない)
- ログは `actions/upload-artifact` で30日間保持
- 手動実行 (`workflow_dispatch`) も可能: サイト指定・モード指定に対応

**手動実行** (`scripts/run_scraper.py`):

```bash
# 全サイト・フルモード
python -m scripts.run_scraper

# 特定サイトのみ
python -m scripts.run_scraper --site truck_kingdom

# 一覧ページのみ (詳細ページスキップ)
python -m scripts.run_scraper --site steerlink --mode listing

# ドライラン (スクレイピング+パースのみ、DB書き込みなし)
python -m scripts.run_scraper --site truck_kingdom --dry-run

# ページ数制限 + JSON出力
python -m scripts.run_scraper --site truck_kingdom --max-pages 3 --dry-run --output results.json
```

主要オプション:

| オプション | デフォルト | 説明 |
|---|---|---|
| `--site` | (全サイト) | 対象サイト (`truck_kingdom` / `steerlink`) |
| `--mode` | `full` | `full` (一覧+詳細) / `listing` (一覧のみ) |
| `--max-pages` | `20` | カテゴリあたりの最大ページ数 |
| `--dry-run` | `false` | DB書き込みをスキップ |
| `--output` | (なし) | 結果をJSONファイルに出力 |
| `--verbose` / `-v` | `false` | デバッグログ出力 |

### 8.6 事故車フィルタリング

現時点では、コード内に事故車・修復歴車を明示的にフィルタリングするロジックは実装されていない。将来的にスクレイピング時またはパース時にタイトルやスペック情報から「事故車」「修復歴あり」等のキーワードを検出してフィルタリングする仕組みの追加が想定される。

### 8.7 Upsert戦略

`ScraperScheduler._upsert_vehicle()` (`scraper/scheduler.py`) が担当する。

**一意キー:** `(source_site, source_id)` の組み合わせで車両を一意に識別する。

**処理フロー:**

```
1. source_site + source_id が空 → "skipped" (スキップ)
2. vehicles テーブルを検索 (source_site + source_id で既存レコードを確認)
3. 既存レコードあり:
   a. price_yen が変化していれば vehicle_price_history に新レコードを挿入
   b. vehicles テーブルを UPDATE → "updated"
4. 既存レコードなし:
   a. vehicles テーブルに INSERT
   b. vehicle_price_history に初期価格を記録 → "new"
```

**外部キー解決:**
- `maker` (メーカー名) → `manufacturers` テーブルから `manufacturer_id` を検索
- `body_type` (架装タイプ) → `body_types` テーブルから `body_type_id` を検索
- `body_type` の `category_id` → `body_types` テーブルから連鎖的に取得
- いずれも見つからない場合は各テーブルの先頭レコードをフォールバック値として使用 (NOT NULL制約への対応)

**価格履歴追跡:**
- 新規レコード挿入時: 初期価格を `vehicle_price_history` に記録
- 既存レコード更新時: 価格が変動していれば `vehicle_price_history` に新エントリを追加

**実行ログ:**
- 各実行は `scraping_logs` テーブルに記録される
- ステータス遷移: `running` → `completed` / `failed`
- 記録内容: `processed_pages`, `new_records`, `updated_records`, `skipped_records`, `error_count`, `error_details`

## 9. 装備オプション・車種マスタ

### 9.1 車種マスタ（vehicle_models）

#### テーブル構造

| カラム名 | データ型 | 説明 |
|---------|---------|------|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `name` | text | 車種名（日本語） |
| `name_en` | text | 車種名（英語） |
| `manufacturer_id` | uuid (FK) | `manufacturers.id` への外部キー |
| `category_code` | text | 車両カテゴリコード（LARGE/MEDIUM/SMALL） |
| `is_active` | boolean | 有効フラグ（デフォルト: `true`） |
| `display_order` | integer | 表示順 |

#### メーカー別モデル一覧（12車種）

| メーカー | 大型 (LARGE) | 中型 (MEDIUM) | 小型 (SMALL) |
|---------|-------------|-------------|-------------|
| 日野 | プロフィア | レンジャー | デュトロ |
| UDトラックス | クオン | コンドル | カゼット |
| 三菱ふそう | スーパーグレート | ファイター | キャンター |
| いすゞ | ギガ | フォワード | エルフ |

各メーカー3車種（大型・中型・小型）で合計12車種が登録されている。

#### メーカー→車種連動ドロップダウン（HTMX）

メーカー選択時、HTMXによりサーバーへ非同期リクエストを送信し、車種ドロップダウンの内容を動的に更新する。

**フロントエンド（simulation.html）:**
```html
<select name="maker" hx-get="/api/v1/masters/models-by-maker"
        hx-target="#model-select" hx-swap="innerHTML"
        hx-trigger="change" hx-include="[name='maker']">
```

**バックエンド（masters.py `get_models_by_maker`）:**
1. `maker_name` パラメータで `manufacturers` テーブルから `id` を検索
2. `vehicle_models` テーブルから該当メーカーの `is_active=True` のモデルを `display_order` 順に取得
3. `<option>` タグのHTML文字列を `HTMLResponse` で返却
4. 末尾に `<option value="__custom__">その他（手動入力）</option>` を自動付与

#### 「その他（手動入力）」オプション

ドロップダウンで「その他（手動入力）」を選択すると、JavaScript関数 `toggleCustomModel()` により：
- テキスト入力フィールド `#model-custom` が表示される（`required` 属性も付与）
- 入力値は `input` イベントリスナーで hidden フィールド `#model-hidden` に同期される
- 通常の車種選択時は hidden フィールドに `select.value` がセットされる

### 9.2 装備オプション（equipment_options）

#### テーブル構造

| カラム名 | データ型 | 説明 |
|---------|---------|------|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `name` | text | オプション名（日本語） |
| `name_en` | text | オプション名（英語） |
| `category` | text | カテゴリコード |
| `estimated_value_yen` | integer | 新品参考価格（円）、デフォルト: `0` |
| `depreciation_rate` | numeric | 年間減価率、デフォルト: `0.150`（15%） |
| `affects_lease_price` | boolean | リース価格影響フラグ、デフォルト: `true` |
| `display_order` | integer | 表示順 |
| `is_active` | boolean | 有効フラグ |

#### カテゴリ別オプション一覧（全22件）

**荷役関連（loading）**

| オプション名 | 新品参考価格 | 年間減価率 |
|-------------|----------:|----------|
| パワーゲート | ¥350,000 | 15% |
| 床フック・ラッシングレール | ¥80,000 | 15% |
| ジョルダー（荷寄せ装置） | ¥200,000 | 15% |
| ウイング開閉装置（電動） | ¥150,000 | 15% |

**クレーン関連（crane）**

| オプション名 | 新品参考価格 | 年間減価率 |
|-------------|----------:|----------|
| 小型クレーン（2.9t吊） | ¥1,500,000 | 15% |
| 中型クレーン（4.9t吊） | ¥2,500,000 | 15% |
| ラジコン操作装置 | ¥300,000 | 15% |

**冷凍冷蔵関連（refrigeration）**

| オプション名 | 新品参考価格 | 年間減価率 |
|-------------|----------:|----------|
| 冷凍ユニット（-25度） | ¥1,200,000 | 15% |
| 冷蔵ユニット（+5度） | ¥800,000 | 15% |
| 二温度帯仕様 | ¥1,800,000 | 15% |
| スタンバイ電源装置 | ¥250,000 | 15% |

**安全装置（safety）**

| オプション名 | 新品参考価格 | 年間減価率 |
|-------------|----------:|----------|
| バックカメラ | ¥80,000 | 15% |
| ドライブレコーダー | ¥50,000 | 15% |
| 衝突被害軽減ブレーキ | ¥200,000 | 15% |
| 車線逸脱警報装置 | ¥120,000 | 15% |

**快適装備（comfort）**

| オプション名 | 新品参考価格 | 年間減価率 |
|-------------|----------:|----------|
| エアサス（全輪） | ¥500,000 | 15% |
| リターダ | ¥350,000 | 15% |
| アルミホイール | ¥200,000 | 15% |
| ハイルーフキャブ | ¥150,000 | 15% |

**その他（other）**

| オプション名 | 新品参考価格 | 年間減価率 |
|-------------|----------:|----------|
| ETC車載器 | ¥30,000 | 15% |
| アルミウイングボディ（特注） | ¥800,000 | 15% |
| ステンレス製荷台 | ¥400,000 | 15% |

> **備考:** 全オプションの `depreciation_rate` デフォルト値は `0.150`（15%/年）。DBスキーマ上は個別設定が可能だが、現行データでは統一値を使用している。

### 9.3 リース料への影響

#### チェックボックス選択→合計自動計算

1. テンプレートで各オプションを `<input type="checkbox" name="equipment" value="{name}" data-value="{estimated_value_yen}">` として出力
2. JavaScriptの `change` イベントリスナーでチェックボックスの変更を検知
3. チェック済みの全チェックボックスの `data-value` 属性値を合算
4. `body_option_value` フィールド（`readonly`）に合計値を自動セット

```javascript
document.addEventListener('change', function(e) {
    if (e.target.name === 'equipment') {
        var total = 0;
        document.querySelectorAll('input[name="equipment"]:checked').forEach(function(cb) {
            total += parseInt(cb.dataset.value || 0);
        });
        document.getElementById('body_option_value').value = total;
    }
});
```

#### Pricing Engineへの受け渡し

- フォーム送信時、`body_option_value`（装備オプション合計額）がPricing Engineに渡される
- 買取上限価格の算出: `_max_purchase_price(book_value, acquisition_price, body_option_value)`
  - `anchor = max(book_value, acquisition_price)`
  - `max_price = int(anchor * 1.10) + body_option_value`
- つまり、装備オプション合計額は簿価/取得価格ベースの上限価格に**そのまま加算**される

### 9.4 UI仕様

#### カテゴリ別チェックボックスグループ

シミュレーション画面（`simulation.html`）では、装備オプションを6つのカテゴリ別にグループ化して表示する。

**カテゴリ定義（テンプレート内ハードコード）:**

| カテゴリコード | 表示ラベル |
|-------------|----------|
| `loading` | 荷役関連 |
| `crane` | クレーン関連 |
| `refrigeration` | 冷凍冷蔵関連 |
| `safety` | 安全装置 |
| `comfort` | 快適装備 |
| `other` | その他 |

**レイアウト仕様:**
- `.checkbox-group`: `display: flex; flex-wrap: wrap; gap: 8px 16px;` でフレックスレイアウト
- `.checkbox-label`: 各チェックボックスとラベルを横並び配置（`align-items: center; gap: 6px`）
- 各オプション名の後に参考価格を `text-muted` スタイルで `(¥xxx,xxx)` 形式表示
- カテゴリ内にオプションが存在しない場合、そのカテゴリグループ自体を非表示（`{% if opts %}`）

**データ取得フロー:**
1. `app/api/pages.py` の `simulation_new_page` でサーバーサイド取得
2. `equipment_options` テーブルから `is_active=True` のレコードを `category, display_order` 順で取得
3. テンプレート変数 `equipment_options` としてJinja2テンプレートに渡す
4. テンプレート側で `category_labels` 辞書のキー順にループし、カテゴリ別に描画

**注意事項:**
- `equipment_options` テーブルはRLSが**無効**（セキュリティ所見あり）
- `vehicle_models` テーブルも同様にRLSが**無効**
- カテゴリコードはDBの `category` カラム値とテンプレートの `category_labels` 辞書キーが一致する必要がある（不一致の場合、該当オプションは表示されない）

## 10. テスト・CI/CD

### 10.1 テスト構成

```
tests/
├── conftest.py                          # 共通フィクスチャ（mock_supabase_client, sample_vehicle_data等）
├── unit/                                # ユニットテスト
│   ├── test_residual_value.py           # 残価計算 (14 tests)
│   ├── test_market_analysis.py          # 市場分析 (17 tests)
│   ├── test_scraper_utils.py            # スクレイパーユーティリティ (40 tests)
│   └── test_pricing.py                  # 価格計算 (35 tests)
├── integration/                         # 統合テスト
│   ├── conftest.py                      # JWT生成・モックSupabase・サンプルデータファクトリ
│   ├── test_api_auth.py                 # 認証API (9 tests)
│   ├── test_api_market_prices.py        # 市場価格API (10 tests)
│   ├── test_api_simulation.py           # シミュレーションAPI (8 tests)
│   └── test_api_masters.py             # マスタAPI (10 tests)
├── e2e/                                 # E2E・モンキーテスト
│   ├── conftest.py                      # E2E用モックSupabase・認証クライアント
│   ├── test_full_workflow.py            # フルワークフロー (6 tests)
│   └── test_monkey.py                   # モンキー/ファズテスト (14 tests)
scripts/
└── qa_e2e_test.py                       # 本番環境向けQA E2Eスクリプト (35 assertions)
```

| カテゴリ | ファイル数 | テストケース数 |
|----------|-----------|---------------|
| Unit tests | 4 | 106 |
| Integration tests | 4 | 37 |
| E2E tests | 1 | 6 |
| Monkey tests | 1 | 14 |
| QA E2E (本番向け) | 1 | 35 assertions |
| **合計** | **11** | **163 + 35** |

### 10.2 テストカバレッジ

- **カバレッジ対象**: `app`, `scraper` パッケージ
- **計測ツール**: `pytest-cov`
- **レポート形式**: XML（CI用アーティファクト） + ターミナル出力（missing行表示）
- **実行コマンド**: `pytest tests/unit -v --cov=app --cov=scraper --cov-report=xml --cov-report=term-missing`

### 10.3 テスト基盤

**pytest設定** (`pytest.ini`):
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
markers =
    e2e: End-to-end tests
    monkey: Monkey/fuzz tests
    slow: Slow tests
```

**共通フィクスチャ**:
- `mock_supabase_client`: チェーン可能なSupabaseクエリビルダーのモック
- `sample_vehicle_data`: 2020年式いすゞエルフ平ボディのテストデータ
- `sample_simulation_input`: リースバックシミュレーション入力サンプル
- `sample_market_data`: 市場データ（中央値・サンプル数・ボラティリティ）

**統合テスト用フィクスチャ** (`tests/integration/conftest.py`):
- `admin_token` / `sales_token`: JWT生成ヘルパー
- `client`: httpx `AsyncClient` + FastAPI依存性オーバーライド（admin認証済み）
- `client_unauthenticated`: 認証なしクライアント（アクセス制御テスト用）
- `client_sales`: salesロールクライアント

**QA E2Eスクリプト** (`scripts/qa_e2e_test.py`):
- 本番URL (`https://auction-ten-iota.vercel.app`) に対して実行
- `requests.Session` でCookie保持しながら全ユーザーフローを検証
- テスト項目: ヘルスチェック、認証、ダッシュボード、KPI API、シミュレーション入力・計算、市場データ、履歴、ログアウト、アクセス制御

### 10.4 CI/CDパイプライン

#### ci.yml — メインCIパイプライン

```
トリガー: push (main, develop) / PR (main)

lint ──→ test ──→ monkey-test
                └─→ e2e-test
```

| ジョブ | 内容 | 詳細 |
|--------|------|------|
| `lint` | 静的解析 | `ruff check .` + `ruff format --check .` |
| `test` | ユニット + 統合テスト | カバレッジ計測、XMLレポートをアーティファクト保存 |
| `monkey-test` | モンキーテスト | `test` 完了後に実行、`-x` フラグで初回失敗停止 |
| `e2e-test` | E2Eテスト | `test` 完了後に実行 |

- Python 3.11, pip キャッシュ有効
- テスト環境変数: `APP_ENV=test`, モック用Supabase認証情報

#### deploy.yml — デプロイパイプライン

```
トリガー: push (main) / workflow_dispatch（手動）

deploy: curl -X POST $RENDER_DEPLOY_HOOK
```

- mainブランチへのpush時にRenderのデプロイフックをHTTP POSTで呼び出し
- `RENDER_DEPLOY_HOOK` はGitHub Secretsで管理

#### scrape.yml — 定期スクレイピング

```
トリガー: cron 0 18 * * * (UTC 18:00 = JST 03:00) / workflow_dispatch（手動）

scrape: matrix [truck_kingdom, steerlink]
```

| 設定 | 値 |
|------|-----|
| スケジュール | 毎日JST 03:00 |
| 並列実行 | `truck_kingdom`, `steerlink` のマトリクス |
| タイムアウト | 120分 |
| fail-fast | false（1サイト失敗しても他は継続） |
| concurrency | `scraping` グループ、進行中キャンセルなし |
| 手動入力 | `site`（対象サイト or "all"）、`mode`（スクレイピングモード） |
| ブラウザ | Playwright + Chromium |
| ログ | アーティファクトとして30日間保存 |

### 10.5 デプロイフロー

| 環境 | 方法 | 詳細 |
|------|------|------|
| **フロントエンド** | Vercel自動デプロイ | `git push` でVercelが自動検知・デプロイ |
| **フロントエンド（手動）** | `vercel --prod` | CLIから本番手動デプロイ |
| **バックエンド** | Render自動デプロイ | mainへのpush時にGitHub Actions経由でRenderデプロイフック呼び出し |
| **スクレイピング** | GitHub Actions | 定期cron or 手動dispatch |

## 11. あるべき姿（将来ビジョン）

Carchsピッチデック「Asset-Backed Alchemy for Commercial Vehicle Lease-Backs」および各仕様書が定義する完全なシステム像と、現行実装（CVLPOS v1.0）とのギャップを以下に整理する。本セクションでは、Phase 2A〜Phase 3にわたる段階的な機能拡充ロードマップと、現時点で未実装の機能一覧を明示する。

---

### 11.1 Phase 2A: LTV/Valuation Stack改修

**目標**: ピッチデックPage 4-5に基づく「B2B卸売相場ベースのLTV 60%ルール」を完全にシステム化し、リテール価格依存から脱却する。

#### 11.1.1 LTV 60%ルールの完全実装

- **現行の課題**: `PricingEngine.calculate_base_market_price()` はオークション価格とリテール価格の加重平均（`auction_weight=0.70`）を使用しており、ピッチデックが定義する「B2B卸売フロア価格の60%を上限とする」ルールと乖離している
- **あるべき姿**:
  - `max_purchase_price = b2b_wholesale_floor × effective_ltv` の厳格適用（`ltv_valuation_spec.md` Section 2.2）
  - `effective_ltv = ltv_ratio(0.60) × category_adjustment × age_adjustment × volatility_adjustment` による段階的安全マージン（実効LTV: 45%〜60%）
  - リテール価格はバリュエーションの入力に**一切使用しない**。参考値としてのみUIに表示
  - 60%超過案件はシステム上 `approval` ステータスへの遷移をハードブロック。ファンドマネージャーの特別承認による最大65%の例外のみ許容
  - `validate_ltv_compliance()` によるリアルタイムLTVコンプライアンスチェック

#### 11.1.2 B2B卸売相場ベースの価格算出

- **あるべき姿**:
  - データソースをB2Bオートオークション成約価格に限定（小売掲載価格を排除）
  - `b2b_wholesale_floor = percentile(P_filtered, 25)` — 第1四分位を保守的基準として採用（`ltv_valuation_spec.md` Section 2.1）
  - IQR法による外れ値除去、90日データ鮮度フィルタ、最小サンプル数5件のフォールバックロジック
  - サンプル3-4件時は `median × 0.85` の保守的割引、3件未満は `MANUAL_REVIEW_REQUIRED` フラグ発行
  - 価格データの3層分類体系: B2B Wholesale / Auction / Retail

#### 11.1.3 オプション調整バリュエーション

- **あるべき姿**:
  - パワーゲート（+5%）、冷凍冷蔵機（+8%）、クレーン（+7%）の各オプション別プレミアム率を個別計算（`ltv_valuation_spec.md` Section 3）
  - プレミアム適格3条件の充足を必須とする: (1) 統計的有意性（10件以上）、(2) 価格プレミアムの実証（5%以上）、(3) プレミアム安定性（CV <= 0.30）
  - `option_premiums` / `vehicle_options` マスタテーブルの新規追加
  - 現行の `SimulationInput.body_option_value` 一律入力からの脱却

---

### 11.2 Phase 2B: ファンド・リース契約管理

**目標**: ピッチデックが定義する3者間スキーム（投資家 - Carchs - 運送会社）の業務フロー全体をシステム化する。

#### 11.2.1 SPC/ファンド管理

- **あるべき姿**:
  - `funds` テーブルによるファンド（SPC）エンティティの管理: ファンドコード、ファンド種別（SPC/GK-TK/TMI）、目標AUM、NAV比率
  - `fund_investors` テーブルによる投資家出資配分の管理: 出資額、持分比率、コミットメント→アクティブ→償還のステータス管理
  - `fund_assets` テーブルによるファンド保有車両の管理: Secured Asset Block (SAB) 概念の実装（`SAB-2026-0001` 形式のID付与）
  - `fund_nav_history` テーブルによるNAV推移の履歴管理
  - 3つのフィーストリームの自動計算: ブローカレッジフィー（買取価格の3%）、マネジメントフィー（AUMの年率2%/12）、グローバルリセール利益
  - ユーザーロールの多段階化: `admin` / `fund_manager` / `investor` / `operator`

#### 11.2.2 リース契約管理

- **あるべき姿**:
  - `lease_contracts` テーブルによる契約管理: 契約番号、開始/終了日、リース期間、月額リース料、残価予測額、保証金
  - `DealStatus` ステートマシンに基づく案件ステータスの遷移管理: `inquiry` → `valuation` → `pricing` → `approval` → `contract` → `transfer` → `disbursed` → `active` → `lease_end` → `remarketing` → `settled`
  - 現行のシミュレーション結果保存のみ（`simulations`テーブル）から、実契約管理への拡張

#### 11.2.3 支払い追跡

- **あるべき姿**:
  - `lease_payments` テーブルによる月次支払いスケジュール・入金追跡: 支払期日、請求額、入金額、入金日、延滞日数
  - 段階的エスカレーションフロー: 支払期日当日（REMINDER）→ +3日（WARNING）→ +7日（ALERT/催告書送付）→ +30日（CURE_PERIOD）→ デフォルト認定
  - 通知マトリクスによる自動通知: リーシー/営業担当/マネージャー/投資家への段階的通知

---

### 11.3 Phase 2C: デフォルト管理・出口戦略

**目標**: ピッチデックPage 8の「T+0→T+10タイムライン」を完全にワークフロー化し、デフォルト発生時にも資産価値を最大化する。

#### 11.3.1 T+0→T+10 ワークフロー

- **あるべき姿**:
  - `DefaultWorkflowEngine` による自動制御: T+0（デフォルト認定）→ T+1（法的シールド自動発動）→ T+3（資産回収/承認要）→ T+10（グローバル清算/承認要）
  - `defaults` / `default_events` テーブルによるデフォルト案件・タイムラインイベントの記録
  - ステージ遷移の妥当性チェック: 許可遷移パスの制限、最小経過日数の検証、承認者の要求
  - 回収コスト項目の管理: レッカー費、保管費、調査費、法的手続費、整備費
  - SPC所有権方式による即時占有回復（従来型銀行融資の数ヶ月〜年単位に対し、T+3日で回収完了）

#### 11.3.2 グローバル清算（7地域）

- **あるべき姿**:
  - 7つの国際地域（東南アジア / 東アフリカ / 西アフリカ / 中東 / 南米 / 旧ソ連諸国 / オセアニア）＋国内の計8市場へのルーティング
  - 車種×地域の需要レベルマトリクス（S/A/B/C/N）と価格プレミアム/ディスカウントテーブルの管理
  - 純清算価値（NLV）の自動算出: `NLV = foreign_market_price - (transport_cost + customs_duty + inspection_cost + misc_cost)`
  - 適格性フィルタ（年式制限・ハンドル規制・排ガス基準）による不適格市場の自動除外
  - 国内再販 vs 海外輸出の利益比較と推奨アクション
  - 地域別輸送コスト・関税・規制データベースの整備（`international_markets` テーブル）

#### 11.3.3 投資家ダッシュボード

- **あるべき姿**:
  - 4画面構成: ポートフォリオサマリー（INV-001）、ファンドパフォーマンス（INV-002）、リスクモニタリング（INV-003）、レポート・帳票（INV-004）
  - KPIカード: 総運用資産額（AUM）、加重平均利回り、Net Fund Asset Value、LTV、デフォルト率
  - Chart.jsによるグラフ群: NFAV推移（60%ラインアノテーション付き）、クロスオーバーチャート（物理的車両価値 vs 累積リース料回収）、利回り実績 vs 目標比較、LTV分布ヒストグラム
  - 60%制約アラートロジック: CRITICAL（< 60%即時通知）、WARNING（< 65%注意喚起）、WATCH（< 70%経過観察）
  - HTMX部分更新パターンによるリアルタイムKPI更新

---

### 11.4 Phase 3: テレメトリー・ESG

**目標**: ピッチデックPage 10「Beyond Financing --- Toward Dynamic Infrastructure Upgrades」のビジョンを実現し、静的評価から動的評価への進化を果たす。

#### 11.4.1 車両IoTデータ連携

- **あるべき姿**:
  - OBD-II / CAN-Bus（J1939）経由のリアルタイムテレメトリーデータ取得
  - 取得データ: 走行距離（累積）、エンジン稼働時間、燃料消費、冷却水温、油温、RPM、DTC（故障コード）、GPS位置情報、バッテリー電圧、DPFすす蓄積率
  - MQTT v5.0 / Webhook受信アーキテクチャ（AWS IoT Core → Redis Streams → 永続化/異常検知/集約）
  - データ保持ポリシー: 生データ30日、1時間集約1年、1日集約5年、異常イベント無期限
  - Phase 3a（テレメトリー基盤構築: 6週間）→ Phase 3b（ダイナミックプライシング: 6週間）→ Phase 3c（ESG・投資家連携: 4週間）の3サブフェーズ

#### 11.4.2 ダイナミックプライシング

- **あるべき姿**:
  - 動的評価式: `dynamic_asset_value = base_market_price × condition_factor × trend_factor × telemetry_health_score × mileage_pace_factor × (1 - safety_margin_rate)`
  - `telemetry_health_score`（0.0〜1.0）: エンジン状態(0.30) + 冷却水温(0.10) + オイル温度(0.10) + DPF状態(0.15) + バッテリー(0.10) + アイドリング比率(0.10) + 急加減速頻度(0.15)
  - `mileage_pace_factor`: 契約走行距離に対する実績ペースによる残価予測の動的補正
  - スナップショット評価から連続的ライブ評価への進化

#### 11.4.3 ESGトランジション支援

- **あるべき姿**:
  - CO2排出量の自動計算（テレメトリーデータベース）
  - ディーゼル→高効率車両へのブリッジキャピタル提供
  - フリート転換支援スキーム
  - ESGメトリクスの投資家向けレポーティング
  - グリーンボンド連携の基盤構築

---

### 11.5 未実装機能一覧

現行CVLPOS v1.0（`https://auction-ten-iota.vercel.app`）と仕様書群が定義するあるべき姿のGAP表。

| # | 領域 | 現行実装 | あるべき姿 | GAP規模 | 対象Phase |
|---|------|---------|-----------|---------|----------|
| 1 | 価格算出ベース | オークション×リテール加重平均（`auction_weight=0.70`） | B2B卸売フロア価格の25パーセンタイル。リテール価格排除 | 大 | 2A |
| 2 | 最大購入価格 | `base_market_price × condition × trend × (1 - safety_margin)` | `b2b_wholesale_floor × effective_ltv`（LTV 60%キャップ厳格適用） | 大 | 2A |
| 3 | バリュエーション3層構造 | auction / retail の2分類のみ | B2B Wholesale / Auction / Retail の3層分離 | 中 | 2A |
| 4 | オプション調整 | `body_option_value` 一律入力 | オプション別プレミアム率（パワーゲート5%、冷凍冷蔵8%、クレーン7%）+ 適格3条件 | 大 | 2A |
| 5 | バリュートランスファーエンジン | 未実装 | `ValueTransferEngine`クラス: NAV月次計算、60%ライン維持検証、インバージョンポイント算出、ストレステスト | 大 | 2A |
| 6 | ファンド（SPC）管理 | 未実装（`users`テーブルのみ） | `funds` / `fund_investors` / `fund_assets` / `fund_nav_history`テーブル群、フィー自動計算 | 大 | 2B |
| 7 | リース契約管理 | `simulations`テーブルでシミュレーション保存のみ | `lease_contracts` / `lease_payments`テーブル、`DealStatus`ステートマシン、支払い追跡ワークフロー | 大 | 2B |
| 8 | デフォルト/出口戦略 | `early_termination_penalty_months: 3`のみ | T+0→T+10タイムライン、`DefaultWorkflowEngine`、段階的エスカレーション、通知マトリクス | 大 | 2C |
| 9 | グローバル清算 | 国内市場スクレイピングのみ | 7地域国際市場ルーティング、NLV算出、適格性フィルタ、輸送コスト/関税データベース | 大 | 2C |
| 10 | 投資家ダッシュボード | 自分のシミュレーション履歴表示のみ | ポートフォリオビュー、NFAV推移グラフ、クロスオーバーチャート、LTV分布、リスク監視 | 大 | 2C |
| 11 | 車両テレメトリー | 未実装 | OBD-II/CAN-Bus連携、MQTT受信基盤、テレメトリーヘルススコア | 大 | 3 |
| 12 | ダイナミックプライシング | 静的パラメータによる`trend_factor`のみ | リアルタイム市場データ + テレメトリーに基づく連続的資産再評価 | 大 | 3 |
| 13 | ESG対応 | 未実装 | CO2排出量計算、グリーンボンド連携、フリート転換支援 | 大 | 3 |
| 14 | ユーザーロール | `authenticated` / `admin` の2段階 | `admin` / `fund_manager` / `investor` / `operator` の多段階RBAC | 中 | 2B |
| 15 | レポーティング | `scripts/export_report.py`のみ | 投資家向け定期レポート（NAV・リスク）、PDF自動生成、配信機能 | 大 | 2C |
| 16 | 二重計算ロジック統合 | `PricingEngine.calculate()` と `calculate_simulation_quick()` が共存し結果不一致 | `PricingEngine`への一本化。簡易版を廃止またはラッパーに変更 | 中 | 2A |
| 17 | CSRF保護 | トークン生成・検証なし（空文字列） | `starlette-csrf`等によるCSRFミドルウェア実装 | 高（セキュリティ） | 即時 |
| 18 | エラーハンドリング | `except Exception: pass` の全面的黙殺 | structlogによるエラーログ出力、ユーザー向けトースト通知、適切なHTTPステータス | 高（品質） | 即時 |

> **注**: 上記GAP #17, #18は`improvement_backlog.md`（IMP-001, IMP-004）で指摘されている品質・セキュリティ課題であり、Phase 2以前に即時対応すべき項目である。
