# CVLPOS 松プラン UI/UX 移行仕様書

**Version:** 1.0
**Date:** 2026-04-22
**Reference wireframe:** `docs/CVLPOS_松プラン_ワイヤーフレーム.html` (1271 lines, React + Chart.js, self-contained)
**Current UI baseline:** `app/templates/` (17 ページ) + `static/css/style.css` (2142行) + `static/js/app.js` + `static/js/dashboard_charts.js`

---

## 0. エグゼクティブサマリー

- **ワイヤーフレームは11画面のプレミアム・リデザイン**(Navy `#0E2747` + Gold `#C9A24A` + クリーム `#F4F3EE` の3色ブランド、Noto Sans JP、Chart.js 4.4)。
- **現状は17テンプレートの青(`#2563eb`)ベース単一テーマ** — CSS変数とパーシャルの素地はあるが、デザイントークンが目標値と異なる。
- **ページ差分:** 6ページが「新規構築」、6ページが「リデザイン」、5ページが「既存維持 + テーマ適用」、1機能(`yayoi_status`)が「吸収」。
- **`static/js/dashboard_charts.js` は既に navy(`#17274D`)+ gold(`#CCB366`)配色** — 目標値に極めて近く、全面書き換え不要。
- **プラン制御(tier gating)は実質未実装** — `松プラン` バッジが1箇所あるのみ。本プランでは tier system を新規導入する必要あり。
- **推奨実装:** 1エージェントで土台(デザイントークン・共有パーシャル・base shell)→ 6〜7エージェントで並列にページ実装 → 1エージェントで tier enforcement。**ピーク並列度 7、総エージェント数 9〜10**(要求の20ではない)。

---

## 1. デザイントークン移行

### 1.1 カラーパレット

| トークン | 現状 | 目標 | 差分 |
|---|---|---|---|
| プライマリ(ブランド) | `--primary: #2563eb` | `--navy: #0E2747` | **全面入れ替え** |
| プライマリ中間 | — | `--navy-2: #143258` | 新規 |
| プライマリ淡 | — | `--navy-3: #1d4272` | 新規(active nav 用) |
| アクセント | — | `--gold: #C9A24A` | 新規 |
| アクセント淡 | — | `--gold-2: #E6C46A` | 新規(KPIヒーロー用) |
| アクセント濃 | — | `--gold-3: #8B6F2C` | 新規 |
| 背景 | `--bg: #f8fafc` | `--bg: #F4F3EE`(クリーム) | 置換 |
| カード | `#ffffff` | `--card: #FFFFFF` | 同じ |
| テキスト | `--text: #1e293b` | `--text: #1F2433` | 微調整 |
| ミュート | `--muted: #64748b` | `--muted: #6E6A5C` | 置換(暖色系へ) |
| 線 | `--border: ?` | `--line: #E2E0D6`, `--line-2: #CFCCBE` | 2段階に拡張 |
| 成功/警告/危険 | `#16a34a / #f59e0b / #dc2626` | `--green: #3E8E5A` / `--amber: #C48A2A` / `--red: #B5443A` | 彩度低め、暖色に寄せる |
| ワイヤープレースホルダ | — | `--wire: #A7A699` | 新規(開発時の空枠用) |

**影響範囲:** `static/css/style.css` の `:root` ブロック全差し替え。テンプレート内の `style=""` ハードコードがあれば併せて置換(Agent Aが `_error_banner.html` で発見済 — 要洗い出し)。

### 1.2 タイポグラフィ

| 項目 | 現状 | 目標 |
|---|---|---|
| サンセリフ | `Inter, Noto Sans JP, system` | `Noto Sans JP, system`(Inter 廃止)|
| 等幅 | `JetBrains Mono, Fira Code` | `JetBrains Mono` 維持 |
| 手書き | — | `Caveat`(付箋風ノート用 `.hand` クラス) |
| 読み込み | `@import`(一部)| Google Fonts の `<link rel="preconnect">` + `<link rel="stylesheet">` で base.html 頭に一元化 |

ウェイト: 300/400/500/600/700/800/900 を Noto Sans JP で明示指定(現状は不明瞭)。

### 1.3 レイアウトプリミティブ

| 項目 | 現状 | 目標 |
|---|---|---|
| サイドバー幅 | 240px | 248px |
| カードの角 R | `--radius` 単一 | 12px(card) / 10px(kpi-sm, inv-card) / 8px(btn, nav-item, input) / 6px(wire) の4段階 |
| カード間隔 | 不明 | 16px(card + card) |
| Grid ギャップ | — | `.grid-2: 16px`, `.grid-3: 16px`, `.grid-4: 12px`, `.kpi-row: 14px` の4パターン |
| Canvas padding | `--space-4` 類 | `26px 28px 60px`(top/x/bottom) |

---

## 2. Base Shell(`app/templates/base.html`)改修

### 2.1 サイドバー

**現状:** ハードコードで 3 リンク(ダッシュボード / シミュレーション / 相場データ)。tier 非対応。

**目標:** データ駆動(Pythonコンテキストから渡された nav config)で 11 リンク、4 グループ、松プラン限定バッジ付き。

```
サマリー
  ・統合ダッシュボード (dashboard)
  ・ポートフォリオ (portfolio) 〔新規〕
パフォーマンス
  ・ファンドパフォーマンス (fund) 〔新規〕
  ・リスクモニタリング (risk) 〔新規・松限定〕 [bg:3]
オペレーション
  ・インベントリ管理 (inv) 〔新規・松強調〕
  ・統合プライシング (price)
  ・契約書自動生成 (contract) ← contract_mapper を昇格
  ・請求書管理・弥生連携 (invoice) ← invoice_list + yayoi_status を統合
松プラン限定
  ・自動価格収集 (scrape) 〔新規・NEW〕
  ・ESGレポート (esg) 〔新規・NEW〕
  ・提案書PDF生成 (proposal) ← proposal_preview を昇格 [NEW]
```

ブランドに `松 Premium` tier バッジ(gold chip)を右寄せ。

サイドバー下部は「システム稼働中 / 全サービス正常」の緑パルスドット。現状の「ログアウトボタン」はトップバーのユーザーチップ配下メニューに移設。

### 2.2 トップバー

**現状:** ハンバーガー + ページタイトルプレースホルダ + ユーザー名 のみ。

**目標:** パンくず / グローバル検索 / ファンドスイッチャ / 通知ベル(カウントバッジ)/ ユーザーチップ(アバター + 名前 + 役割).

- パンくず: `ホーム / {current_page_title}`
- 検索: 「車両ID、契約番号、運送会社で検索…」プレースホルダ(Phase 3 以降の実装でOK、Phase 1 では UI のみ)
- ファンドスイッチャ: 5ファンドのプルダウン(`localStorage.cvl_fund` 永続化)
- 通知ベル: 未読件数バッジ(Phase 3 以降の実装、Phase 1 は UI のみ)
- ユーザーチップ: 「安田 修 / 投資家・LP」等(`current_user.display_name` と `stakeholder_role`)

### 2.3 共有固定パネル

- **`.var-bar`**(右下): ダッシュボードのみ表示、A/B/C 切替
- **`.tweaks`**(右上): 編集モード時のみ表示。`window.postMessage('__activate_edit_mode')` で起動。本番では非表示。

---

## 3. 共有パーシャル再編(`app/templates/partials/`)

### 3.1 新規作成

| パーシャル | 用途 |
|---|---|
| `_sidebar.html` | データ駆動のサイドバー(nav config を context で受ける) |
| `_topbar.html` | パンくず + 検索 + ファンドスイッチ + ユーザーチップ |
| `_kpi_hero.html` | KPIヒーロー(variant A/B/C 対応、Jinja マクロで切替) |
| `_kpi_sm.html` | 小KPIカード(`.ok` / `.warn` / `.bad` 状態) |
| `_card.html` | カード枠(header/body スロット、card-h / card-b) |
| `_chip.html` | チップマクロ(ok/warn/bad/info/neutral) |
| `_alert.html` | アラート枠(red/amber) |
| `_tabs.html` | タブ(active のアンダーライン gold) |
| `_lbar.html` | 線形プログレスバー |
| `_inv_card.html` | インベントリカード(プレート + メタ + LTV) |
| `_var_bar.html` | ダッシュボードのバリアント切替 |
| `_tweaks_panel.html` | 編集モードパネル |
| `_fund_switcher.html` | ファンド切替ドロップダウン |

### 3.2 改修

| パーシャル | 変更 |
|---|---|
| `_error_banner.html` | インラインスタイル排除 → `.alert.red` に寄せる |
| `kpi_cards.html` | `_kpi_sm.html` に統一、既存呼出し箇所を差し替え |
| `invoice_table.html` | 「弥生連携」列追加、ステータスチップを新パレットに |
| `market_prices_table.html` | 新しい `.tbl` クラスに合わせたスタイル調整 |
| `chart_fragment.html` | `ChartCanvas` 相当の lifecycle を持つ(`htmx:afterSettle` で再初期化) |
| `pagination.html` | 新パレットに合わせて再スタイリング(機能は維持) |

### 3.3 アイコンシステム

現状: なし(絵文字 🚚 やCDN画像に散発的に依存)

目標: `static/icons/` に SVG パス定義を集約する JS モジュール(`icons.js`)。wireframe の `ICONS` オブジェクト(20種)をそのまま移植。各パーシャルで `{{ icon('dash', 18) }}` マクロ呼出し。

---

## 4. ページ別ギャップ分析

凡例: **N** = 新規構築 / **R** = リデザイン(構造 + スタイル)/ **T** = テーマ適用のみ / **A** = 他ページに吸収

### 4.1 ワイヤーフレーム側の11画面 → 現状マッピング

| # | Wireframe page | 現状テンプレート | 分類 | 主な変更点 |
|---|---|---|---|---|
| 1 | Dashboard(ポートフォリオ・コックピット) | `dashboard.html` | **R** | KPIヒーロー(variant A/B/C)/ NAV推移チャート / AUMドーナツ / ファンド一覧表 / リアルタイムアラート 3件。`dashboard_charts.js` 拡張(既に navy/gold 配色済) |
| 2 | Portfolio(ポートフォリオサマリー) | ー | **N** | LTV分布横棒 + 加重利回り推移線 + KPIヒーロー(A)。LP/投資家ビュー |
| 3 | Fund(ファンドパフォーマンス) | ー | **N** | NFAV推移 / クロスオーバー月 / IRR(Bull/Base/Bear) / タブ4種。既存 `financial_analysis.html` のロジック流用可 |
| 4 | Risk(リスクモニタリング) | ー | **N** | **松プラン限定** / アラート表(CRITICAL/WARN) + 操作ボタン + KPI4(High risk / 延滞 / NFAV警戒 / システムヘルス) |
| 5 | Price(統合プライシング) | `integrated_pricing.html` | **R** | 3ステップ構成は維持、**Bull/Base/Bear 3シナリオ比較表を追加**、推奨行を gold ハイライト |
| 6 | Contract(契約書自動生成) | `contract_mapper.html` | **R** | 9種チェックボックス UI + パラメータ自動流し込み表 + 「ZIP 一括ダウンロード」gold ボタン |
| 7 | Invoice(請求書管理・弥生連携) | `invoice_list.html` + `invoice_detail.html` + `yayoi_status.html` | **R + A** | **弥生連携機能を invoice_list に統合**(yayoi_status は廃止または吸収)、「弥生と同期」「一括生成」ボタン、KPI4(今月発行 / 入金済 / 承認待 / 延滞)、テーブルに「弥生連携」列 |
| 8 | Inventory(インベントリ管理) | ー | **N** | **松プラン強調** / フリートKPIヒーロー + タブフィルタ(全/稼働/要注意/延滞/償却)+ 142台のカードグリッド(プレート画像 + メタ + LTV) |
| 9 | Scrape(自動価格収集) | ー | **N** | **松プラン限定 NEW** / 5ソース(AI-NET/TK/USS/TAA/JU)ジョブ表 + 正規化パイプライン可視化 + プロキシ健全状況 |
| 10 | ESG(ESGレポート) | ー | **N** | **松プラン限定 NEW** / E/S/G 3カード + テンプレートグリッド4種 + PDF自動生成ボタン |
| 11 | Proposal(提案書PDF生成) | `proposal_preview.html` | **R** | 入力パラメータカード + A4×8ページのプレビュー枠グリッド(P.1-P.8)+ 「PDF 出力」gold ボタン |

### 4.2 現状側にあってワイヤーフレームに対応なしのページ

| 現状テンプレート | 分類 | 扱い |
|---|---|---|
| `login.html` | **T** | テーマ適用のみ(Navy/Gold + Noto Sans JP)。レイアウト維持 |
| `forgot_password.html` | **T** | 同上 |
| `simulation.html` | **T** | シミュレーション入力フォーム。整合プライシングとは別フロー、**維持**。新デザイントークンを適用。サイドバーにリンクは無いが URL は維持(/simulation/new → Priceから誘導) |
| `simulation_list.html` | **T** | シミュレーション履歴。維持、テーマ適用。Portfolio ページからリンク |
| `simulation_result.html` | **T** | 結果表示。維持、テーマ適用 |
| `market_data_list.html` | **T** | 相場データ一覧。Scrape ページの下位ビュー(ドリルダウン先)として位置づけ直し、URL 維持 |
| `market_data_detail.html` | **T** | 同上、相場データ詳細。ドリルダウン先 |
| `market_data_import.html` | **T** | CSV インポート。Scrape ページから "手動インポート" として導線を張る |
| `lease_contract_import.html` | **T** | リース契約インポート。Inventory ページから "一括登録" で誘導 |
| `financial_analysis.html` | **A** | **Fund ページの「IRR / NFAV」タブに吸収**する方向で検討(ロジック流用)。既存URLは当面維持してリダイレクト |
| `yayoi_status.html` | **A** | **Invoice ページに統合**、URL 廃止。既存エンドポイント `/yayoi/*` API は維持 |

### 4.3 新規ページ計6本(N 分類)

1. **Portfolio**
2. **Fund**
3. **Risk** 🔒 松限定
4. **Inventory** ✨ 松強調
5. **Scrape** 🔒 松限定 NEW
6. **ESG** 🔒 松限定 NEW

---

## 5. Tier Gating(プラン制御)システム

### 5.1 現状

`app/templates/pages/yayoi_status.html:6` に装飾バッジ `<span>松プラン</span>` が1箇所存在するのみ。ルート側の権限チェックもテンプレート側の条件分岐も無い。

### 5.2 目標

**ユーザーのプラン階層(梅 / 竹 / 松)** を元に、ナビ・ページ・機能を出し分ける。

#### 5.2.1 ユーザーモデル拡張

`app/models/` の User/Stakeholder 型に以下を追加(Supabase `users` テーブルに列追加が必要):

```python
class UserPlan(str, Enum):
    ume = "ume"   # 梅
    take = "take" # 竹
    matsu = "matsu" # 松
```

`stakeholder_role` に加えて `plan: UserPlan` フィールドを追加。既存レコードのデフォルトは `take`(竹)とする(安全側)。

#### 5.2.2 ゲート仕様

| 画面/機能 | 梅 | 竹 | 松 |
|---|---|---|---|
| Dashboard(variant A) | ✓ | ✓ | ✓ |
| Dashboard(variant B/C) | ー | ー | ✓ |
| Portfolio | ✓ | ✓ | ✓ |
| Fund | ✓ | ✓ | ✓ |
| **Risk** | ー | ー | **✓ 松限定** |
| Price | ✓ | ✓ | ✓ |
| Contract(9種一括) | ー | 3種のみ | **✓ 9種** |
| Invoice(弥生連携) | ー | 閲覧のみ | **✓ 双方向 + 承認WF** |
| Inventory | 簡易 | 標準 | **✓ + テレマティクス** |
| **Scrape** | ー | ー | **✓ 松限定 NEW** |
| **ESG** | ー | ー | **✓ 松限定 NEW** |
| Proposal | ー | ✓ | ✓ |

#### 5.2.3 実装メカニクス

- **バックエンド**: `app/middleware/plan_gate.py` に `require_plan(UserPlan.matsu)` 依存関数を追加(`require_permission` と同様のパターン)。ルート側で `Depends(require_plan("matsu"))` をかける。プラン不足は 402 Payment Required または 403 + アップグレード案内 JSON を返す。
- **テンプレート側**: `base.html` の context に `current_plan` を注入。サイドバー nav config を `{"label": "...", "required_plan": "matsu"}` 形式にして、Jinja で `{% if user_can_access(item) %}` 判定。
- **アップグレード動線**: 下位プランのユーザーが上位ページにアクセス試みた場合、専用 `upgrade_prompt.html` を返す(cta「松プランへ」)。

### 5.3 バッジ表示規則

- **`松プラン限定`**(gold タグ、`page-head .tag`): Risk, Scrape, ESG, Dashboard ヒーロー右肩
- **`松プラン 強調機能`**(同): Inventory
- **`NEW`**(gold 丸バッジ、`nav-item .new`): Scrape, ESG, Proposal のサイドバーアイテム右端

---

## 6. データ・バックエンド要件

### 6.1 既存エンドポイントの流用

| ページ | 既存API | 追加要件 |
|---|---|---|
| Dashboard | `/api/v1/dashboard/kpi/json` | AUM・NFAV・LTV・稼働車両を返す拡張(ファンド別集計) |
| Portfolio | 同上(LP スコープで絞込) | `stakeholder_role=investor` 向けのフィルタ付与 |
| Fund | `/api/v1/simulations/*` 系を流用 | NFAV時系列、クロスオーバー計算の集計SQL |
| Price | `/api/v1/pricing/calculate` | Bull/Base/Bear 3シナリオ同時算出(既存は Base のみ?要確認) |
| Contract | `/api/v1/contracts/mapper/{id}` | 9種 ZIP 一括生成(既存は個別PDF) |
| Invoice | `/api/v1/invoices/*` | 既存を流用、`yayoi_sync` フラグ列を request/response に含める |
| Proposal | `/api/v1/proposals/generate` | 既存(本日3-bug wave で RFC 5987 修正済)を流用 |

### 6.2 新規バックエンドが必要な機能

| ページ | 新規 API | 備考 |
|---|---|---|
| Risk | `/api/v1/risk/alerts`, `/api/v1/risk/thresholds` | しきい値設定 + アラート取得 |
| Inventory | `/api/v1/vehicles/fleet` | 142台のカード表示用集計 |
| Scrape | `/api/v1/scrape/jobs`, `/api/v1/scrape/run/{job_id}` | ジョブ一覧 + 実行。既存 `/scrape` は別タスクでCRONワーカー化が必要 |
| ESG | `/api/v1/esg/metrics`, `/api/v1/esg/report` | CO2 / 事故 / RBAC 集計 + PDF生成 |

**Phase 1-2では フィクスチャデータで UI を先行実装** し、バックエンドは Phase 3 で追いつく戦略を推奨(ワイヤーフレーム自身もそうなっている → `※ ワイヤーフレーム用のシミュレーション。実データは本実装時に接続されます` のノート参照)。

---

## 7. ロードマップ(フェーズ分割)

### Phase 1: デザイン基盤(Design Foundation)

**期間目安:** 1スプリント(1-2日)
**並列度:** 1 エージェント(逐次、土台のため全員が依存)

- [ ] 新 CSS トークン(`static/css/tokens.css` or `style.css` の `:root` 置換)
- [ ] Google Fonts 読み込み(Noto Sans JP / JetBrains Mono / Caveat)
- [ ] Base shell(`base.html`)の刷新: 248px サイドバー、トップバー再設計
- [ ] データ駆動サイドバー(`_sidebar.html` パーシャル + nav config)
- [ ] 共有パーシャル群(`_kpi_hero`, `_kpi_sm`, `_card`, `_chip`, `_alert`, `_tabs`, `_lbar`, `_inv_card`, `_fund_switcher`, `_topbar`, `_var_bar`, `_tweaks_panel`)
- [ ] アイコンシステム(`static/icons.js` に ICONS 辞書移植)
- [ ] `dashboard_charts.js` のカラー変数を新トークンに合わせて微調整(#17274D → #0E2747, #CCB366 → #C9A24A)
- [ ] 既存ページが壊れないか smoke テスト(全17テンプレートを手動 or TestClient でロード)

**ブロッカー条件:** Phase 1 が完了するまで Phase 2 以降の並列実装は開始しない(全員が新パーシャルに依存するため)。

### Phase 2: 既存ページの再テーマリング(R/T 分類)

**期間目安:** 2-3スプリント
**並列度:** 6 エージェント

| G | エージェント | 対象 | 所有ファイル |
|---|---|---|---|
| G2-1 | Dashboard リデザイン + A/B/C variant | `dashboard.html`, `dashboard_charts.js` | 独占 |
| G2-2 | Price リデザイン + Bull/Base/Bear | `integrated_pricing.html` | 独占 |
| G2-3 | Contract リデザイン + 9種一括 | `contract_mapper.html` | 独占 |
| G2-4 | Invoice リデザイン + 弥生吸収 | `invoice_list.html`, `invoice_detail.html`, `yayoi_status.html` 廃止 | 独占(3ファイル) |
| G2-5 | Proposal リデザイン + 8ページプレビュー | `proposal_preview.html` | 独占 |
| G2-6 | Simulation/Market/Auth テーマ適用 | `simulation*.html`, `market_data*.html`, `login.html`, `forgot_password.html`, `lease_contract_import.html`, `financial_analysis.html` | 独占(まとめてテーマ適用のみ) |

**file lock risk:** 各エージェントは異なるテンプレートを所有。`base.html`, `tokens.css`, パーシャルへは触らない(Phase 1 で確定済)。

### Phase 3: 新規ページ(N 分類、6本)

**期間目安:** 3-4スプリント
**並列度:** 6 エージェント(バックエンドはフィクスチャでモック、API は Phase 4 で実装)

| G | エージェント | 対象 |
|---|---|---|
| G3-1 | Portfolio | `app/templates/pages/portfolio.html` + ルート `/portfolio` |
| G3-2 | Fund | `app/templates/pages/fund.html` + ルート `/fund`(financial_analysis のロジック流用) |
| G3-3 | Risk(松限定) | `app/templates/pages/risk.html` + ルート `/risk` + `require_plan("matsu")` |
| G3-4 | Inventory(松強調) | `app/templates/pages/inventory.html` + ルート `/inventory` |
| G3-5 | Scrape(松限定 NEW) | `app/templates/pages/scrape.html` + ルート `/scrape` + `require_plan("matsu")` |
| G3-6 | ESG(松限定 NEW) | `app/templates/pages/esg.html` + ルート `/esg` + `require_plan("matsu")` |

### Phase 4: Tier Enforcement + バックエンドAPI

**期間目安:** 2-3スプリント
**並列度:** 1-2 エージェント(全ルートを触るため安全優先)

- [ ] `app/middleware/plan_gate.py` 実装(`require_plan(plan)` 依存関数)
- [ ] `User` / `Stakeholder` モデルに `plan` フィールド追加 + 既存レコードマイグレーション
- [ ] Phase 3 で作った6ページのルートに `require_plan` を適用
- [ ] `upgrade_prompt.html` + `/upgrade` フロー
- [ ] サイドバーの tier-aware 条件分岐
- [ ] バックエンドAPI実装(Risk/Inventory/Scrape/ESG の新規4セット)

### Phase 5: 仕上げ

**期間目安:** 1スプリント
**並列度:** 1 エージェント

- [ ] ダッシュボードの A/B/C variant 切替(`.var-bar`)+ localStorage 永続化
- [ ] ファンドスイッチャ(全ページで `localStorage.cvl_fund` で絞込)
- [ ] 通知ベル(未読件数の実データ連携)
- [ ] モバイルレスポンシブ調整
- [ ] アクセシビリティ(aria-label, focus order)
- [ ] visual regression テスト(Playwright で主要画面のスクリーンショット diff)

---

## 8. 並列化計画(なぜ20エージェントではないのか)

**ピーク並列度: Phase 3 の 6 エージェント**。 ユーザー要求「20エージェント」は、以下の理由で非現実的:

1. **Phase 1 は逐次**(全員が同じ `base.html` / パーシャルに依存する土台)。1エージェントで完了させてから次へ。
2. **Phase 2 は6並列が上限** — それ以上に分けると、同じテンプレートに触るエージェントが発生し、worktree間マージで衝突する。
3. **Phase 3 も6並列** — 新規ページ6本を別エージェントに割ると自然に分かる。
4. **Phase 4 はルート/DBマイグレーションで全ルートに触るため 1-2 エージェント**。
5. 10 エージェントを超えると、**レビュー/マージのキューが詰まる**(親エージェントのボトルネック)。

**総使用エージェント数(目安):** 1(P1)+ 6(P2)+ 6(P3)+ 2(P4)+ 1(P5)= **16 エージェント/延べ**、ただし並列ピークは 6。

---

## 9. 未決事項(ユーザー確認事項)

1. **Tier 階層の名前** — `ume / take / matsu` の3段階で正しいか、他の命名(`basic / pro / enterprise` 等)を使うか。
2. **`yayoi_status.html` 廃止の可否** — 既存ユーザーがブックマークしている可能性。リダイレクトでOKか、廃止扱いで 404 でもよいか。
3. **`simulation*` ページの扱い** — ワイヤーフレームには存在しないが現状の中核機能。サイドバーから消すか、`Price` ページの「個別シミュレーション」としてサブリンクに入れるか。
4. **Chart.js vs 代替** — 現状 CDN で Chart.js 4。ワイヤーフレームも Chart.js 4。このままで良いか、もしくは Recharts/ApexCharts に乗せ換えか(推奨は維持)。
5. **編集モード(`.tweaks` パネル)を本番に残すか** — デザイン調整用途。開発時のみで良いか、CS/CSチーム向けに一部公開するか。
6. **バックエンドAPI実装の担当** — 本仕様書では Phase 4 に含めたが、バックエンド実装は別チーム(別スプリント)の可能性。並行実装か逐次か。
7. **A/B/C variant の運用** — Phase 5 で実装予定だが、ユーザー側で切り替えるのか、投資家ロール別に固定するのか(例:LP は A、AM は B、Risk 担当は C)。
8. **ESGレポートの算出ロジック** — CO2 排出量、事故件数、RBAC実装済みなど、**データソース未定**。先行して UI のみ実装、実データは Phase 4 以降で別途設計。
9. **ファンド数の扱い** — ワイヤーフレームは 5 ファンド固定(カーチスファンド 11-15号)。将来的にファンド追加時のスイッチャ拡張が必要か。

---

## 10. 参考資料

- **本仕様書の元データ:**
  - `docs/CVLPOS_松プラン_ワイヤーフレーム.html`(目標)
  - `app/templates/` 全17テンプレート(現状)
  - `static/css/style.css`(2142行、ハンドライトCSS)
  - `static/js/app.js`(HTMX + Chart.js lifecycle)
  - `static/js/dashboard_charts.js`(既に navy/gold 配色済、上書き元)

- **前提・関連memory:**
  - 2026-04-22 3-bug wave(CSRF/latin-1/RBAC)は完了・push済(`7adfb2d`)
  - Render + Vercel 両系にデプロイ中

---

**次のアクション候補(ユーザー承認待ち):**
1. 本仕様書で進めてよい → Phase 1(1エージェント、逐次)を起動
2. 未決事項(セクション9)に先に回答
3. 仕様書を調整(スコープ削減、画面追加、etc.)
