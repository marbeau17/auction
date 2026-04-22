# 使用書: 個別シミュレーション & 契約書自動生成

**Date:** 2026-04-22
**Scope:** `/simulation/new` (個別シミュレーション) と `/simulation/{id}/contracts` (契約書自動生成) の仕様 + 現状の問題点 + 修正方針。
**Context:** 松プラン UI redesign (commits `a94bc46`..`1cb8555`) 後、両ページがバックエンドに到達していないことが 2026-04-22 の本番確認で判明。

---

## 1. 個別シミュレーション

### 1.1 エンドポイント
- **ページ URL:** `GET /simulation/new`
- **テンプレート:** `app/templates/pages/simulation.html`
- **表示:** フォーム(車両情報 + リース条件 + オプション)

### 1.2 ユーザーフロー

```
サイドバー「オペレーション > 個別シミュレーション」
  ↓
/simulation/new (フォーム入力画面)
  ↓ [メーカー選択]→ GET /api/v1/masters/models-by-maker?maker=X (HTMX chained)
  ↓ [モデル選択]
  ↓ [その他の項目入力]
  ↓ [算出ボタン]
POST /api/v1/simulations/calculate (HTMX hx-post, hx-target="#result-area")
  ↓ 結果フラグメント返却
#result-area にインライン表示
  ↓ [保存ボタン]
POST /api/v1/simulations/save → /simulation/{id}/result にリダイレクト
  ↓ 結果画面から「契約書生成」「提案書PDF」「再計算」
```

### 1.3 依存API(既存・動作中)

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/masters/makers` | メーカー一覧(初期ドロップダウン) |
| `GET` | `/api/v1/masters/models-by-maker?maker=X` | HTMX chained モデル選択 |
| `GET` | `/api/v1/masters/body-types` | 車体タイプ |
| `GET` | `/api/v1/masters/categories` | 車格 |
| `POST` | `/api/v1/simulations/calculate` | 計算(line 628 of `app/api/simulation.py`) |
| `POST` | `/api/v1/simulations/save` | 保存 |

### 1.4 現状の問題点

1. **マスターデータが empty** — 本番 Supabase の `makers` / `models` / `body_types` / `categories` テーブルに seed データが入っていない(または RLS でアクセス拒否)ため、フォーム起動時にドロップダウンが空になり、ユーザーが入力できない。
2. **フォールバックなし** — 現状の `simulation.html` は `makers` が空なら選択肢なしで表示するだけ。
3. **計算結果のサンプル表示がない** — ユーザーが試しに入力しても「なんとなく動く」感覚が得られない。

### 1.5 修正方針

- **Seed データの挿入**: `supabase/migrations/20260422000002_seed_masters_sample.sql`(新規)で makers/models/body_types/categories に最低限のサンプル(いすゞ / 日野 / 三菱ふそう / トヨタ × 各 3〜5 車種)を INSERT。
- **Python-level fallback**: `app/services/sample_data.py`(新規)に fixture を定義、`/simulation/new` のルートハンドラで Supabase 取得失敗時にフィクスチャを返す。
- **Calculate 結果は既存ロジックのまま**: PricingEngine は入力さえ揃えば動く。

---

## 2. 契約書自動生成

### 2.1 エンドポイント
- **ページ URL:** `GET /simulation/{simulation_id}/contracts`
- **テンプレート:** `app/templates/pages/contract_mapper.html`
- **表示:** シミュレーションに紐づく 9 種の契約書を一括生成する UI

### 2.2 ユーザーフロー

```
シミュレーション結果画面「契約書を生成」
  ↓
/simulation/{id}/contracts (ページロード)
  ↓ 既存実装では…
GET /api/v1/contracts/mapper/{simulation_id} (HTMX load → ページ全体置換)
  ↓ Mapper HTML がフラグメントを返し、ステークホルダー編集 UI を表示
  ↓ [ステークホルダー情報入力]
POST /api/v1/contracts/stakeholders (個別保存)
  ↓ [契約書の種類を選択(9種チェックボックス)]
  ↓ [9種まとめて生成ボタン]
POST /api/v1/contracts/generate/{simulation_id}
  → DOCX 9 ファイルを生成、deal_contracts テーブルに記録
  ↓
各契約書のダウンロードリンクが結果として返る
```

### 2.3 依存API(既存・動作中)

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/contracts/mapper/{simulation_id}` | **メインフラグメント(すべてのUIがこれで返る)** |
| `GET` | `/api/v1/contracts/types` | 契約書9種の種類マスター |
| `POST` | `/api/v1/contracts/stakeholders` | ステークホルダー個別保存 |
| `PUT` | `/api/v1/contracts/stakeholders/{id}` | ステークホルダー更新 |
| `DELETE` | `/api/v1/contracts/stakeholders/{id}` | ステークホルダー削除 |
| `GET` | `/api/v1/contracts/addressbook` | アドレスブック一覧 |
| `GET` | `/api/v1/contracts/addressbook/options/{role_type}` | ロール別候補 |
| `POST` | `/api/v1/contracts/addressbook/save` | アドレスブック保存 |
| `POST` | `/api/v1/contracts/generate/{simulation_id}` | **9種一括生成(DOCX)** |
| `POST` | `/api/v1/contracts/stakeholders/copy/{src}/{tgt}` | 別シミュから複製 |

### 2.4 現状の問題点(CRITICAL)

Phase 2-3 リデザイン時、エージェント G2-3 は存在しないエンドポイントにボタンを結線していた:

| テンプレートが呼出し | 実在 |
|---|---|
| `GET /api/v1/contracts/bulk-zip/{simulation_id}` | ❌ |
| `GET /api/v1/contracts/preview/{simulation_id}` | ❌ |
| `POST /api/v1/contracts/generate-all/{simulation_id}` | ❌ |

結果として、**「ZIP 一括ダウンロード」「プレビュー」「9種まとめて生成 →」の全ボタンが無反応**。

加えて、ページ全体のコンテンツは本来**Mapper フラグメント**が動的に差し込む設計(HEAD~7 の `contract_mapper.html`):

```jinja
<div id="mapper-content"
     hx-get="/api/v1/contracts/mapper/{{ simulation_id }}"
     hx-trigger="load"
     hx-swap="innerHTML">
    <div class="loading-placeholder">読み込み中...</div>
</div>
```

Phase 2-3 の書き換えで、このロード部分も削除されてしまった。

### 2.5 修正方針

**前回の機能をそのまま流用**(ユーザー指示):

1. **`contract_mapper.html` の役割を再定義**:
   - **シェル部分**(page-head, 9種チェックボックス UI, パラメータカード) — 松プランデザインを維持
   - **ステークホルダー編集 + 生成ボタン部分** — Mapper フラグメント(`GET /api/v1/contracts/mapper/{id}`)の既存実装を HTMX でロード
2. **ボタンの修正**:
   - 「9種まとめて生成 →」→ `POST /api/v1/contracts/generate/{simulation_id}?types=A,B,C,...`(types はチェックボックス値の comma-separated)
   - 「プレビュー」→ Mapper フラグメント内のプレビュー機能に置き換え、もしくは削除(既存UIは Mapper が持っている)
   - 「ZIP 一括ダウンロード」→ `POST /api/v1/contracts/generate/{id}` のレスポンスにZIP 用 URL を追加する、もしくは一時的に削除
3. **`app/api/contracts.py` に `/bulk-zip/{id}` エンドポイントを追加**(任意、松プラン強調機能として):
   - `POST /api/v1/contracts/generate/{id}` の内部ロジックを呼び、DOCX → ZIP 化してレスポンス

---

## 3. サンプルデータ投入方針(横断)

### 3.1 目的
「全ての機能がなんとなく動く」体験を、Supabase 接続なし or 空でも提供する。

### 3.2 方針
- 新規モジュール `app/services/sample_data.py` に、fixture を一元管理(現在は各テンプレートに散在)
- 対象: Dashboard / Portfolio / Fund / Risk / Inventory / Scrape / ESG / Invoice / Simulation masters
- ルートハンドラで Supabase アクセスが失敗 or 空なら fixture を返す try/except
- 既存のインライン `{% set %}` を段階的に置換

### 3.3 対象データ

| ドメイン | データ | 件数 |
|---|---|---|
| Masters | makers, models, body_types, categories | 4 × 3-5 |
| Funds | ファンド 11-15号 | 5 |
| Vehicles | インベントリ | 5-20 |
| Invoices | 請求書 | 6-142 (wireframe は 6 visible) |
| Alerts | Risk alerts | 3 |
| Scrape jobs | AI-NET / TK / USS / TAA / JU | 5 |
| NAV series | 月次 36 ヶ月 | 1 per fund |
| ESG inputs | 既存 `esg_service.py` の fixture を使う | — |
| Contract stakeholders sample | ロール別デフォルト | 8-10 |

---

## 4. ダークモード / ライトモード

### 4.1 方針
- `body[data-theme="dark"]` を切替、CSS 変数をダーク用にオーバーライド
- トグルUI: トップバー右(ベル左隣)に ☀/🌙 ボタン
- `localStorage.cvl_theme` で永続化
- デフォルト: OS 設定(`prefers-color-scheme`)を尊重

### 4.2 ダークモード時のトークン上書き例
```css
body.matsu[data-theme="dark"] {
  --bg: #0f1520;
  --card: #1a2332;
  --line: #2a3547;
  --line-2: #374257;
  --text: #E6E4DB;
  --muted: #9A968A;
  /* navy / gold は維持(ブランド色) */
}
```

---

## 5. 実装ユニット分解(エージェント配分)

ユーザー希望: 10 エージェント。**実際の作業単位ベースで push back して 5 エージェント**を提案:

| # | エージェント | 担当 | ファイル |
|---|---|---|---|
| 1 | **Contract 修復** | contract_mapper の Mapper フラグメントロード復帰 + 正しいエンドポイントへの結線 + /bulk-zip エンドポイント新設 | `contract_mapper.html`, `app/api/contracts.py` |
| 2 | **Simulation サンプル対応** | `app/services/sample_data.py` の masters 部分 + ルートハンドラで fixture フォールバック | `app/services/sample_data.py`, `app/api/pages.py` (simulation ルート) |
| 3 | **ダークモード** | CSS tokens, トグル UI, JS、`_topbar.html` | `matsu-components.css`, `_topbar.html`, `app.js` |
| 4 | **サンプルデータ横断 A** | Dashboard / Portfolio / Fund のサンプル化 | `sample_data.py` + 3 テンプレート |
| 5 | **サンプルデータ横断 B** | Inventory / Risk / Scrape / Invoice のサンプル化 | `sample_data.py` + 4 テンプレート |

10 人にすると、1 つの `sample_data.py` を複数エージェントが奪い合う状態になり、マージで衝突する。5 人でも `sample_data.py` は 2 人(#2, #4, #5)が同時に触る — これは逐次(#2 → #4 → #5)で回避。

---

## 6. 検証基準(完了条件)

- [ ] `/simulation/new` のメーカードロップダウンに 4 件以上の選択肢が出る
- [ ] 計算ボタン押下で結果が表示される(フィクスチャでも可)
- [ ] `/simulation/{id}/contracts` ページロードで Mapper フラグメントが読み込まれる
- [ ] 「9種まとめて生成 →」ボタンで実際に `/api/v1/contracts/generate/{id}` が叩かれる
- [ ] ダークモード切替で全ページが視覚的に反転する
- [ ] Dashboard / Portfolio / Fund / Risk / Inventory / Scrape / Invoice が、Supabase 空でも fixture データで表示される
- [ ] pytest に新規回帰なし
