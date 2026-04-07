# API監査レポート

- **対象システム**: https://auction-ten-iota.vercel.app
- **実施日時**: 2026-04-07
- **実施者**: QAエンジニア（自動監査）
- **認証ユーザー**: admin@carchs.com (role: admin)

---

## 総合サマリー

| 項目 | 件数 |
|------|------|
| テスト総数 | 20 |
| PASS | 18 |
| FAIL | 1 |
| WARN | 1 |

---

## 全エンドポイント結果一覧

### ページエンドポイント

| # | メソッド | エンドポイント | ステータス | レスポンス種別 | サイズ(bytes) | 判定 | 備考 |
|---|----------|---------------|-----------|---------------|--------------|------|------|
| 1 | GET | `/` | 302 | - (リダイレクト) | 0 | PASS | `/dashboard` へリダイレクト。正常動作 |
| 2 | GET | `/login` | 200 | HTML | 3,959 | PASS | ログインページ正常表示 |
| 3 | GET | `/dashboard` | 200 | HTML | 15,394 | PASS | ダッシュボード正常表示 |
| 4 | GET | `/simulation/new` | 200 | HTML | 22,145 | PASS | 新規シミュレーション画面正常表示 |
| 5 | GET | `/market-data` | 200 | HTML | 33,919 | PASS | 市場データ一覧正常表示 |
| 6 | GET | `/market-data/{vehicle_id}` | 200 | HTML | 10,274 | PASS | 車両詳細ページ正常表示 (ID: `a24f294c-...`) |
| 7 | GET | `/simulation/{id}/result` | 200 | HTML | 6,110 | PASS | シミュレーション結果ページ正常表示 (ID: `bde62519-...`) |

### APIエンドポイント

| # | メソッド | エンドポイント | ステータス | レスポンス種別 | サイズ(bytes) | 判定 | 備考 |
|---|----------|---------------|-----------|---------------|--------------|------|------|
| 8 | GET | `/health` | 200 | JSON | 15 | PASS | `{"status":"ok"}` |
| 9 | GET | `/api/v1/dashboard/kpi` | 200 | HTML | 588 | PASS | HTMXフラグメント返却（HTML部品）。KPI: 今月査定数=3件, 平均利回り=8.7%, 市場データ数=64件 |
| 10 | POST | `/api/v1/simulations/calculate` | 200 | HTML | 25,789 | PASS | HTMXフラグメントでシミュレーション結果を返却。正常計算完了 |
| 11 | GET | `/api/v1/simulations` | 200 | JSON | 9,892 | PASS | 8件のシミュレーション結果を返却。ページネーション正常 |
| 12 | GET | `/api/v1/masters/makers` | **500** | JSON | 35 | **FAIL** | `{"detail":"Failed to fetch makers"}` -- サーバー内部エラー |
| 13 | GET | `/api/v1/masters/body-types` | 200 | JSON | 2,361 | PASS | 10件のボディタイプを返却 |
| 14 | GET | `/api/v1/masters/categories` | 200 | JSON | 1,162 | PASS | 5件のカテゴリを返却 |
| 15 | GET | `/api/v1/masters/models-by-maker?maker_name=日野` | 200 | HTML | 288 | PASS | HTMXフラグメント（`<option>`タグ）。プロフィア、レンジャー等を返却 |
| 16 | GET | `/api/v1/market-prices` | 307 -> 200 | JSON | 15,746 | WARN | 307リダイレクトが発生（末尾スラッシュ補正の可能性）。リダイレクト後は正常にJSONデータ返却 |
| 17 | GET | `/api/v1/market-prices/statistics` | 200 | JSON | 129 | PASS | 統計情報正常: count=64, avg=7,305,000円, median=5,075,000円 |

### 認証エンドポイント

| # | メソッド | エンドポイント | ステータス | レスポンス種別 | サイズ(bytes) | 判定 | 備考 |
|---|----------|---------------|-----------|---------------|--------------|------|------|
| 18 | POST | `/auth/login` (正常) | 302 | - (リダイレクト) | 0 | PASS | `/dashboard` へリダイレクト。Cookie (`access_token`, `refresh_token`) 正常発行 |
| 19 | POST | `/auth/login` (不正) | 302 | - (リダイレクト) | 0 | PASS | `/login?error=メールアドレスまたはパスワードが正しくありません。` へリダイレクト。適切なエラーハンドリング |
| 20 | POST | `/auth/logout` | 302 | - (リダイレクト) | 0 | PASS | `/login` へリダイレクト。Cookie正常クリア (`Max-Age=0`) |
| 21 | GET | `/auth/me` | 200 | JSON | 87 | PASS | `{"id":"bc163b83-...","email":"admin@carchs.com","role":"admin"}` |

---

## 検出された問題

### FAIL: `/api/v1/masters/makers` が 500 Internal Server Error を返却

- **重要度**: 高
- **ステータスコード**: 500
- **レスポンスボディ**: `{"detail":"Failed to fetch makers"}`
- **影響範囲**: メーカーマスタデータの取得が不可能。ただし、`/simulation/new` ページ自体は正常表示されるため、ページ内で別の方法でメーカーデータを取得している可能性あり。
- **推奨対応**: サーバーサイドログを確認し、データベース接続またはクエリの問題を特定・修正すること。

### WARN: `/api/v1/market-prices` で 307 リダイレクトが発生

- **重要度**: 低
- **詳細**: 初回リクエスト時に 307 Temporary Redirect が発生。おそらく末尾スラッシュの正規化（`/market-prices` -> `/market-prices/`）によるもの。
- **影響**: フロントエンドからのHTMXリクエストでは問題にならないが、API単体利用時にはレイテンシが増加する。
- **推奨対応**: ルート定義で末尾スラッシュの統一を検討。

---

## アーキテクチャ所見

| 項目 | 内容 |
|------|------|
| フレームワーク | FastAPI (Python) |
| フロントエンド | サーバーサイドレンダリング (Jinja2テンプレート) + HTMX |
| API設計 | REST API (`/api/v1/`) とHTMXフラグメント返却が混在 |
| 認証方式 | JWT (ES256) をHttpOnly Cookieで管理。SameSite=lax, Secure設定済み |
| ホスティング | Vercel |
| データベース | Supabase (PostgreSQL) |

### Content-Typeに関する注記

一部のAPIエンドポイントは `application/json` ではなく `text/html` を返却する。これはHTMXパターン（サーバーからHTMLフラグメントを返却し、クライアント側でDOM挿入する設計）に基づくものであり、意図的な設計である。

- `/api/v1/dashboard/kpi` -> HTML (HTMXフラグメント)
- `/api/v1/simulations/calculate` -> HTML (HTMXフラグメント)
- `/api/v1/masters/models-by-maker` -> HTML (`<option>`タグ)

---

## セキュリティ確認事項

| チェック項目 | 結果 |
|-------------|------|
| HTTPS強制 | HSTS有効 (`max-age=63072000; includeSubDomains; preload`) |
| Cookie HttpOnly | 有効 |
| Cookie Secure | 有効 |
| Cookie SameSite | lax |
| ログアウト時Cookie削除 | 有効 (`Max-Age=0` で即時失効) |
| 不正ログイン時のエラーメッセージ | 汎用メッセージ使用（メールorパスワード不正を区別しない）-- 適切 |

---

## 結論

全20エンドポイント中、18件が正常動作（PASS）、1件がサーバーエラー（FAIL）、1件が軽微な問題（WARN）。

**最優先対応事項**: `/api/v1/masters/makers` エンドポイントの500エラーを修正すること。メーカーマスタはシミュレーション新規作成時に必要な基幹データであり、本番環境での障害として早急な対応が必要。
