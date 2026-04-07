# CVLPOS 改善バックログ

**作成日:** 2026-04-06
**対象バージョン:** 1.0（本番: https://auction-ten-iota.vercel.app）
**レビュー方法:** コード精査 + ユーザーフロー分析

---

## 優先度: 高

### IMP-001: CSRF保護が未実装 -- XSS/CSRF攻撃に対して脆弱
- **現状:** テンプレートに `<meta name="csrf-token">` タグがあり、`static/js/app.js` (L7-11) と `login.html` (L82-84) でヘッダー注入JSが存在するが、バックエンド側でCSRFトークンの生成・検証を一切行っていない。`{{ csrf_token }}` は常に空文字列。
- **問題:** POST `/auth/login`, POST `/auth/logout`, POST `/api/v1/simulations` 等の状態変更エンドポイントがCSRF攻撃に対して無防備。認証済みユーザーのセッションを悪用されるリスクがある。
- **改善案:** FastAPIミドルウェアでCSRFトークンを生成しCookieに設定。Jinja2テンプレートにトークンを渡し、POSTリクエスト時にサーバー側で検証する。`starlette-csrf` パッケージの導入を推奨。
- **影響範囲:** `app/main.py`, `app/api/auth.py`, `app/api/simulation.py`, 全テンプレート
- **工数見積:** 1日

### IMP-002: シミュレーションフォームの年式フィールドがYYYY-MM形式と不一致
- **現状:** `SimulationInput.registration_year_month` は `YYYY-MM` 形式を期待（`app/models/simulation.py` L18-21, 例: `"2020-04"`）。しかしシミュレーションフォーム（`simulation.html` L59-61）では年のみの `<select>` で `2026`, `2025` 等の値を送信。
- **問題:** `PricingEngine.calculate()` (`app/core/pricing.py` L236-238) で `reg_ym.split("-")` を実行するため、月なしの値（例: `"2024"`）だとIndexErrorまたは不正な経過月数算出となり計算が破綻する。`calculate_simulation_quick` (L679) ではregexで年だけ抽出して回避しているが、正規の `create_simulation` パスでは問題が発生。
- **改善案:** フォームに月選択も追加するか、バックエンド側で年のみの入力を `YYYY-01` にデフォルト変換するバリデーションを追加。
- **影響範囲:** `app/templates/pages/simulation.html`, `app/models/simulation.py`, `app/core/pricing.py`
- **工数見積:** 0.5日

### IMP-003: シミュレーション結果の保存とHTMXレスポンスの不整合
- **現状:** シミュレーションフォームは `hx-post="/api/v1/simulations/calculate"` (L17) に送信するが、`calculate_simulation_quick` (`app/api/simulation.py` L628) は認証不要で結果をDBに保存しない。一方 `create_simulation` (L318) はJSON bodyを期待し `SimulationInput` でバリデーションするため、`application/x-www-form-urlencoded` のフォーム送信では422エラーとなる。
- **問題:** 実質的にフォームから実行されるシミュレーションは保存されない。ダッシュボードやシミュレーション履歴に表示されるのは別経路（JSONリクエスト）で作成されたもののみ。デモで「シミュレーション実行 -> 履歴確認」の一貫したフローが成立しない。
- **改善案:** `calculate_simulation_quick` の結果もDBに保存するか、フォーム送信をJS経由でJSON化して `create_simulation` に送るように統合。ユーザーにとっては「実行したら自動的に履歴に残る」が自然。
- **影響範囲:** `app/api/simulation.py` (L620-), `app/templates/pages/simulation.html`
- **工数見積:** 1日

### IMP-004: エラーハンドリングの全面的な黙殺（silent failure）
- **現状:** `app/api/pages.py` の全ページハンドラー（L96-114, L147-150, L219-220, L244-245, L320-321, L477-478）で `except Exception: pass` パターンが多用されている。DB接続エラー、テーブル未存在、権限エラー等すべてが飲み込まれ、ユーザーには空データが表示される。
- **問題:** 本番でSupabaseの接続障害やスキーマ変更が発生してもユーザーに一切通知されない。デバッグが極めて困難。ダッシュボードのKPIが全て0になっても原因が分からない。
- **改善案:** 最低限エラーログ出力を追加（structlogは既に導入済み）。ユーザー向けにはトースト通知やエラーバナーを表示。重大エラー時は適切なHTTPステータスを返す。
- **影響範囲:** `app/api/pages.py` 全体, テンプレートのエラー表示コンポーネント
- **工数見積:** 1日

---

## 優先度: 中

### IMP-005: パスワードリセット機能の未実装
- **現状:** ログインページ (`login.html` L66) に「パスワードを忘れた方」リンク (`/auth/forgot-password`) が存在するが、対応するエンドポイントもテンプレートも存在しない。クリックすると404エラー。
- **問題:** デモ時に顧客がクリックすると破綻したUXを露呈する。本番運用でもパスワードリセットは必須機能。
- **改善案:** Supabase Authの `reset_password_for_email` APIを利用したリセットフロー実装。最低限、リンクを非表示にするか「準備中」表示に変更。
- **影響範囲:** `app/api/auth.py`, 新テンプレート `forgot_password.html`
- **工数見積:** 1日

### IMP-006: 二重の計算ロジックによる結果不一致
- **現状:** シミュレーション計算が2系統存在する。(A) `PricingEngine.calculate()` (`app/core/pricing.py` L197-385) -- 本格的な市場価格分析・トレンド・安全マージン計算を実装。(B) `calculate_simulation_quick()` (`app/api/simulation.py` L628-) -- 簡易版で `_max_purchase_price`, `_monthly_lease_fee` 等のヘルパー関数を使用。
- **問題:** 同じ入力に対して(A)と(B)で異なる結果が出る。(B)は `recommended_price = max_price * 0.95` (L673) というハードコード、保険料/メンテ費が固定値 `15000/10000` (L706, L775)。(A)はパラメータ化された精緻な計算。デモの信頼性を損なう。
- **改善案:** フォーム送信パスも `PricingEngine.calculate()` を使うよう統合。`calculate_simulation_quick` は廃止するか、`PricingEngine` のラッパーに変更。
- **影響範囲:** `app/api/simulation.py`, `app/core/pricing.py`
- **工数見積:** 2日

### IMP-007: シミュレーション結果ページのDB列名不一致
- **現状:** `simulation_result.html` は `simulation.purchase_price_yen`, `simulation.lease_monthly_yen`, `simulation.total_lease_revenue_yen`, `simulation.expected_yield_rate` 等のDB列を参照（L22-34）。しかし `SimulationRepository.create()` (`simulation_repo.py` L56-72) は `input_data` と `result` をJSONとして保存しており、これらのフラット列がDBに存在するかはスキーマ次第。
- **問題:** `simulation_result.html` で表示される値が全て0または `--` になる可能性がある。`result_summary_json` (L57) の参照も不確実。保存されたシミュレーションの結果詳細ページが正しく表示されない。
- **改善案:** テンプレートを `simulation.result` JSONから値を取得するように修正するか、`SimulationRepository.create()` でフラット列にも値をマッピングして保存。
- **影響範囲:** `app/templates/pages/simulation_result.html`, `app/api/pages.py` (L162-228), `app/db/repositories/simulation_repo.py`
- **工数見積:** 1日

### IMP-008: 市場データのページネーション不完全
- **現状:** 初期表示（`market_data_list_page` in `pages.py` L254-334）では20件のみ表示し、ページネーションUIは件数表示のみ（`market_data_list.html` L191-193 `{{ total_count }}件`）。HTMXフィルターのテーブルフラグメント（`market_data_table_fragment` L337-445）にはページネーション計算があるが、初期ロードでは使われない。
- **問題:** 全件数が表示されるが次ページへの遷移手段がない。フィルタ操作後のHTMXレスポンスにもページネーションUIが含まれていない（`market_prices_table.html` の内容次第）。
- **改善案:** 初期表示でもHTMXフラグメント経由でテーブルを読み込むか、`market_data_list.html` にページネーションコンポーネントを追加。
- **影響範囲:** `app/templates/pages/market_data_list.html`, `app/templates/partials/market_prices_table.html`, `app/api/pages.py`
- **工数見積:** 0.5日

### IMP-009: CORS設定がローカルホストのみ -- 本番ドメイン未登録
- **現状:** `app/main.py` (L101-113) で `allowed_origins` は `localhost:8000`, `localhost:3000`, Supabase URLのみ。本番ドメイン `auction-ten-iota.vercel.app` が含まれていない。
- **問題:** 現状はHTMX（同一オリジンリクエスト）のためCORSエラーは発生しないが、将来的にSPAフロントエンドやモバイルアプリからのAPI利用時に問題となる。また `allow_methods=["*"]`, `allow_headers=["*"]` は過剰に緩い。
- **改善案:** 本番ドメインを `allowed_origins` に追加。`allow_methods` と `allow_headers` を必要最小限に制限。環境変数で管理。
- **影響範囲:** `app/main.py`, `app/config.py`
- **工数見積:** 0.5日

---

## 優先度: 低

### IMP-010: 結果ページのチャート生成が簡易的 -- PricingEngineの詳細スケジュールを未活用
- **現状:** `simulation_result_page` (`pages.py` L183-218) でチャートデータを生成する際、保存済みシミュレーションの `purchase_price`, `lease_monthly`, `lease_term` から単純な定額法で再計算。残価率は `0.20 if term <= 36 else 0.10` のハードコード (L192)。`PricingEngine` が計算した詳細な `monthly_schedule`（各月の `asset_value`, `depreciation_expense`, `financing_cost`, `monthly_profit` 等）は使われていない。
- **問題:** チャートの値が実際のシミュレーション結果と乖離。PricingEngineは架装別減価償却テーブル・走行距離補正・200%定率法を考慮しているが、チャートは単純定額法。投資家向けデモとしての説得力が低い。
- **改善案:** シミュレーション保存時に `monthly_schedule` もJSON列として保存し、結果ページではそのデータからチャートを生成。
- **影響範囲:** `app/api/pages.py` (L162-228), `app/db/repositories/simulation_repo.py`, `app/templates/pages/simulation_result.html`
- **工数見積:** 1日

---

## 補足: その他の検出事項

| # | カテゴリ | 内容 | 該当ファイル |
|---|---------|------|-------------|
| A | セキュリティ | `APP_SECRET_KEY` のデフォルト値が `"change-me"` (`config.py` L9)。本番でも変更されていない可能性 | `app/config.py` |
| B | セキュリティ | `calculate_simulation_quick` (L628) が認証不要。非ログインユーザーでもAPIを叩ける | `app/api/simulation.py` |
| C | データ品質 | 市場データ取得時にメーカー名の完全一致フィルタ (`eq("maker", maker)`)。表記揺れ（「いすゞ」vs「いすず」）で類似車両がヒットしない | `app/api/simulation.py` L723-726 |
| D | UX | 「条件変更して再計算」ボタン (`simulation_result.html` L138) が `/simulation/new` に遷移するだけで前回の入力値を引き継がない | `app/templates/pages/simulation_result.html` |
| E | UX | ダッシュボードの「相場変動アラート」KPI (`dashboard.html` L43-44) は実際にはアクティブ車両数を表示しており、名称と実態が不一致 (`pages.py` L104-105) | `app/api/pages.py`, `dashboard.html` |
| F | パフォーマンス | 市場データ統計計算で全件の `price_yen` を取得 (`pages.py` L296-313)。データ量増加時にレスポンス遅延の原因に | `app/api/pages.py` |
| G | UX | `base.html` の sidebar で `current_user.display_name` を参照 (L57) するが、テンプレートに `current_user` は渡されない（`user` 変数で渡されている）。サイドバーのユーザー名が空欄 | `app/templates/base.html` |
| H | コード品質 | HTMLフラグメントをPython文字列で組み立て (`simulation.py` L153-232, L235-298)。XSSリスクあり、メンテ困難。Jinja2テンプレートに移行すべき | `app/api/simulation.py` |
