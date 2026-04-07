# UI/UX 監査レポート - 商用車リースバック価格最適化システム (CVLPOS)

**監査日**: 2026-04-06  
**対象**: フロントエンド テンプレート・CSS・JavaScript 全体  
**技術スタック**: Jinja2テンプレート / HTMX 1.9.12 / Chart.js 4.x / カスタムCSS (BEM命名規則)

---

## 1. 画面一覧と現在の状態

### 1.1 ログイン画面 (`pages/login.html`)

**画面構成**:
- `base.html` を継承しない独立ページ (`login-page` ボディクラス)
- ダークグラデーション背景 (`#1e293b` -> `#334155`) の中央にカード配置
- カード幅: 最大420px

**表示要素**:
- トラック絵文字アイコン (&#x1F69A;)
- システム名タイトル (日本語 + 英語サブタイトル)
- メールアドレス入力 (`type="email"`, `autocomplete="email"`, `autofocus`)
- パスワード入力 (`type="password"`, `autocomplete="current-password"`, `minlength="8"`)
- 「ログイン状態を保持」チェックボックス
- 「パスワードを忘れた方」リンク (`/auth/forgot-password`)
- ログインボタン (`.btn--primary .btn--block .btn--lg`)
- フッターに著作権表示

**HTMXインタラクション**:
- フォーム送信: `hx-post="/auth/login"` -> エラー表示を `#login-error` にswap
- ローディングインジケーター: `#login-spinner` (`.htmx-indicator .spinner`)
- 送信中はボタン無効化: `hx-disabled-elt="#login-submit"`
- 成功時: `HX-Redirect` ヘッダーを受けて `window.location.href` でリダイレクト
- CSRFトークン: `meta[name="csrf-token"]` から取得し `X-CSRF-Token` ヘッダーに注入

**レスポンシブ**: カード自体は `max-width: 420px` で中央揃えのため、モバイルでも問題なし

---

### 1.2 ダッシュボード (`pages/dashboard.html`)

**画面構成**:
- `base.html` 継承 (サイドバー + メインコンテンツ レイアウト)
- `active_page == 'dashboard'` でサイドバーのアクティブ状態制御

**表示要素**:

1. **ページヘッダー**: 「ダッシュボード」タイトル + 説明文
2. **KPI カードグリッド** (`.kpi-grid`, 3列グリッド):
   - シミュレーション数 (アイコン: クリップボード, 青色背景)
   - 平均利回り (アイコン: ドル記号, 緑色背景)
   - 相場変動アラート (アイコン: 警告三角, 黄色背景) - アラートがある場合は詳細リンク表示
3. **クイックアクションボタン** (`.actions-row`):
   - 「新規シミュレーション」ボタン (`btn--primary btn--lg`, `/simulation/new`)
   - 「相場データ確認」ボタン (`btn--outline btn--lg`, `/market-data`)
4. **最近のシミュレーション一覧** (`.card`):
   - テーブルヘッダー: タイトル / 車種・年式 / 買取価格 / 月額リース / 利回り / ステータス / 実行日
   - ステータスバッジ: 完了(緑) / 実行中(青) / エラー(赤) / 下書き(グレー)
   - 各行のタイトルは結果詳細画面へのリンク
   - データなし時: 空状態メッセージ表示

**HTMXインタラクション**:
- `#recent-simulations` が60秒ごとに自動ポーリング (`hx-trigger="every 60s"`)
- ダッシュボード全体を再取得し、`hx-select` で該当部分のみ抽出

**レスポンシブ**: KPIカードはモバイルで1列、タブレットで2列に変更

---

### 1.3 シミュレーション画面 (`pages/simulation.html`)

**画面構成**:
- `base.html` 継承
- 2列フォームグリッド (`.form-grid`) - 左: 車両情報 / 右: リース条件

**表示要素**:

**左列 - 車両情報**:
1. メーカー選択 (`<select>`, 必須)
2. 車種選択 (`<select>`, カスタム入力切替可能) + 手動入力テキストフィールド
3. 年式選択 (2026年〜2010年) + 走行距離入力 (number, 横並び `.form-row`)
4. クラス選択 + ボディタイプ選択 (横並び)
5. 取得価格入力 + 簿価入力 (横並び)
6. **装備オプションセクション**: カテゴリ別チェックボックスグループ
   - 荷役関連 / クレーン関連 / 冷凍冷蔵関連 / 安全装置 / 快適装備 / その他
   - 各オプションに推定価値 (円) 表示
7. 架装オプション合計価格 (自動計算、読み取り専用)

**右列 - リース条件**:
1. 目標利回り (number, 1〜30%, step 0.1, デフォルト 8)
2. リース期間 (12/24/36/48/60ヶ月、デフォルト24ヶ月)

**アクションボタン**:
- リセットボタン (`btn--outline`)
- シミュレーション実行ボタン (`btn--primary btn--lg`) + スピナー

**結果表示エリア**: `#result-area` (空div、HTMXでフラグメント注入)

**HTMXインタラクション**:
- メーカー変更 -> `hx-get="/api/v1/masters/models-by-maker"` で車種ドロップダウン更新
- フォーム送信 -> `hx-post="/api/v1/simulations/calculate"` -> `#result-area` に結果表示
- ローディング: `#calc-spinner`

**JavaScript**:
- `toggleCustomModel()`: 車種選択で「その他」選択時にテキスト入力表示
- チェックボックス変更時に装備オプション合計を自動計算

**レスポンシブ**: `.form-row` はモバイルで1列に変更

---

### 1.4 シミュレーション結果画面 (`pages/simulation_result.html`)

**画面構成**:
- `base.html` 継承
- シミュレーションデータがある場合とない場合で分岐表示

**表示要素** (データあり):
1. **ページヘッダー**: シミュレーションタイトル + ID(先頭8文字) + 作成日 + ステータスバッジ
2. **KPIグリッド** (`.kpi-grid`, 4枚のカード):
   - 買取価格 / 月額リース料 + 期間 / リース料総額 / 想定利回り
3. **車両情報カード**: テーブル形式 (車種名/年式/走行距離/市場参考価格/リース期間)
4. **計算結果詳細カード** (result_summary_json がある場合のみ): 買取価格/市場価格/月額リース料/実質利回り
5. **アクションボタン**:
   - 「条件変更して再計算」(`btn--outline`, `/simulation/new`)
   - 「ダッシュボードへ」(`btn--primary`, `/dashboard`)

**表示要素** (データなし):
- エラーメッセージ + ダッシュボードへの戻りボタン

**Chart.js**: この画面自体にはチャートなし (パーシャル版 `simulation_result_fragment.html` にはあり)

---

### 1.5 相場データ一覧 (`pages/market_data_list.html`)

**画面構成**:
- `base.html` 継承
- フィルターバー + データテーブル

**表示要素**:
1. **ページヘッダー**: 「相場データ」+ 全件数表示
2. **フィルターバー** (`.filter-bar`):
   - メーカー選択 / ボディタイプ選択 / 年式範囲 (開始〜終了) / 価格帯 (万円、下限〜上限) / キーワード検索
   - フィルターリセットボタン
3. **データテーブル** (`.data-table`):
   - ヘッダー: メーカー / 車種 / 年式 / 走行距離 / 価格 (税込/税別/ASK表示) / 架装 / 所在地
   - 各行クリックで詳細画面遷移 (`.table__row--clickable`)
   - ローディングプレースホルダー (`.loading-placeholder`)
4. **ページネーション**: 総件数表示 (簡易版、フルページネーションはパーシャルから)

**HTMXインタラクション**:
- 全フィルター要素が `hx-trigger="change"` で即座にテーブル更新
- キーワード検索: `hx-trigger="change, keyup changed delay:400ms"` (400msデバウンス)
- テーブル行クリック: `hx-get="/market-data/{id}"`, `hx-push-url="true"` でSPA的遷移
- ローディングインジケーター: `#table-loading`

**レスポンシブ**: フィルターフォームはモバイルで縦並びに変更

---

### 1.6 相場データ詳細 (`pages/market_data_detail.html`)

**画面構成**:
- `base.html` 継承
- 戻るリンク付きページヘッダー

**表示要素** (車両データあり):
1. **ページヘッダー**: 戻るリンク(SVGアイコン付き) + メーカー・車種名 + タグ (年式/ボディタイプ/積載量)
2. **価格カード** (`.result-card--info`): 販売価格 (税込/税別表記) + 万円換算
3. **車両スペック** (`.detail-grid`): 10項目の定義リスト
   - メーカー / 車種 / 年式 / 走行距離 / 積載量 / ボディタイプ / ミッション / 燃料 / 所在地 / 掲載ステータス
4. **類似車両テーブル** (`.data-table--hover`):
   - メーカー・車種 / 年式 / 走行距離 / 価格 / 詳細ボタン
5. **アクション**: 「この車種でシミュレーション」ボタン (`btn--primary btn--lg`, maker/model パラメータ付き)

**表示要素** (車両なし):
- 戻るリンク + 「車両が見つかりません」メッセージ + 一覧へ戻るボタン

---

### 1.7 パーシャルテンプレート一覧

| ファイル | 用途 | HTMXスワップ対象 |
|---------|------|----------------|
| `kpi_cards.html` | ダッシュボードKPIカード (トレンド表示付き) | `#kpi-cards` |
| `simulation_result_fragment.html` | シミュレーション結果のHTMXフラグメント (8枚のサマリーカード + Chart.js棒グラフ + 月次スケジュールテーブル) | `#simulation-result` |
| `vehicle_table.html` | 車両データテーブル + ページネーション | `#vehicle-table-container` |
| `market_prices_table.html` | 相場データテーブル + OOBスワップ (stats-count/stats-avg/stats-median) | `#vehicle-table-container` |
| `model_options.html` | メーカー別車種ドロップダウンオプション | `#model-select` |
| `market_reference.html` | 相場参考パネル (価格範囲/中央値/サンプル数/トレンド) | `#market-reference` |
| `chart_fragment.html` | 汎用Chart.jsフラグメント (line/bar対応) | `#chart-container` |
| `validation_error.html` | バリデーションエラー表示 (フィールド別エラーリスト) | 任意のエラー表示エリア |
| `toast.html` | トースト通知 (success/error/warning/info + SVGアイコン + アニメーション) | `.toast-container` |
| `recent_simulations.html` | 最近のシミュレーション簡易テーブル (4列) | `#recent-simulations` |

### 1.8 コンポーネント一覧

| ファイル | 用途 |
|---------|------|
| `components/pagination.html` | ページネーションUI (前へ/次へ + ページ番号 + 省略記号) |
| `components/navbar.html` | サイドバーナビゲーション (代替版、HTMXによるSPA遷移対応) |
| `components/form_field.html` | 再利用可能フォームフィールドマクロ (text/select/textarea対応、バリデーションエラー表示付き) |

---

## 2. デザインシステム

### 2.1 カラーパレット

#### ライトモード
| 変数名 | 値 | 用途 |
|--------|-----|------|
| `--primary` | `#2563eb` | メインブランドカラー (青) |
| `--primary-hover` | `#1d4ed8` | ホバー状態 |
| `--primary-light` | `#dbeafe` | 背景アクセント |
| `--danger` | `#dc2626` | エラー・危険 (赤) |
| `--success` | `#16a34a` | 成功・完了 (緑) |
| `--warning` | `#f59e0b` | 警告 (黄) |
| `--info` | `#0ea5e9` | 情報 (水色) |
| `--bg` | `#f8fafc` | ページ背景 |
| `--bg-white` | `#ffffff` | カード背景 |
| `--text` | `#1e293b` | メインテキスト |
| `--text-muted` | `#64748b` | 補助テキスト |
| `--text-light` | `#94a3b8` | 薄いテキスト |
| `--border` | `#e2e8f0` | ボーダー |
| `--border-dark` | `#cbd5e1` | 強調ボーダー |

#### ダークモード (`prefers-color-scheme: dark`)
| 変数名 | 値 |
|--------|-----|
| `--bg` | `#0f172a` |
| `--bg-white` | `#1e293b` |
| `--text` | `#e2e8f0` |
| `--text-muted` | `#94a3b8` |
| `--border` | `#334155` |
| `--border-dark` | `#475569` |
| サイドバー背景 | `#0c1222` |
| ログイン背景 | `#020617` -> `#0f172a` |

**所見**: Tailwind CSS のカラースケール (Slate系) をベースとした統一的なパレット。ダークモードは `prefers-color-scheme` メディアクエリによるシステム連動のみ (手動切替UIなし)。

### 2.2 タイポグラフィ

| 変数名 | 値 | 用途 |
|--------|-----|------|
| `--font-sans` | `"Inter", "Noto Sans JP", -apple-system, ...` | 本文 |
| `--font-mono` | `"JetBrains Mono", "Fira Code", ui-monospace` | コード |
| `--text-xs` | `0.75rem` (12px) | バッジ、注釈 |
| `--text-sm` | `0.875rem` (14px) | ラベル、テーブル |
| `--text-base` | `1rem` (16px) | 本文 |
| `--text-lg` | `1.125rem` (18px) | ヘッダータイトル |
| `--text-xl` | `1.25rem` (20px) | セクションタイトル |
| `--text-2xl` | `1.5rem` (24px) | ページタイトル |
| `--text-3xl` | `1.875rem` (30px) | KPI数値 |

**所見**: Inter + Noto Sans JP の組み合わせは日英混在に適している。ただし、フォントファイルのローカル読み込みや `@font-face` 宣言がなく、ブラウザのフォールバックに依存している。

### 2.3 コンポーネントライブラリ

#### カード (`.card`)
- 白背景 / ボーダー / 小さなシャドウ
- ヘッダー (`.card__header`): flexbox、タイトル + リンク
- ボディ (`.card__body`): パディング付き / flush版 (パディングなし)
- フッター (`.card__footer`): 背景色付き
- ホバーでシャドウ強調

#### ボタン (`.btn`)
- バリエーション: `--primary` / `--outline` / `--ghost` / `--text` / `--danger`
- サイズ: `--sm` / (default) / `--lg` / `--block`
- disabled状態: opacity 0.5 + cursor not-allowed

#### バッジ (`.badge`)
- pill形状 (border-radius: 9999px)
- バリエーション: `--success` / `--warning` / `--danger` / `--primary` / `--neutral`

#### テーブル (`.data-table`)
- stickyヘッダー
- ホバーハイライト (`.data-table--hover`)
- ストライプ (`.data-table--striped`)
- `.table-responsive` でオーバーフロースクロール

#### フォーム
- `.form-group` / `.form-label` / `.form-input` / `.form-select`
- 必須マーク: `.form-label--required` (CSS `::after` で赤い `*`)
- エラー状態: `.is-error` クラス
- フォーカス: 青ボーダー + 青いボックスシャドウ
- `.form-row`: 2列グリッド
- `.form-hint`: ヘルプテキスト

#### KPIカード (`.kpi-card`)
- アイコン + ボディ (ラベル + 値 + 補足) の横並び
- アイコンバリエーション: `--primary` / `--success` / `--warning` / `--danger`
- ホバーでY軸-1pxの浮き上がりアニメーション

#### 結果カード (`.result-card`)
- 左ボーダーアクセント付き
- バリエーション: `--primary` / `--info` / `--success` / `--warning` / `--danger` / `--neutral`

#### ページネーション (`.pagination`)
- 前へ / ページ番号 / 省略記号 / 次へ
- アクティブ状態: 青背景白文字
- disabled状態: aria-disabled対応

#### トースト (`.toast`)
- 右上固定位置
- スライドイン + フェードアウトアニメーション
- 3.6秒後に自動消去
- success (緑) / error (赤) / warning (黄)

#### フィルターバー (`.filter-bar`)
- 白背景カード内にフォーム要素をflexbox配置
- 範囲入力 (`~` セパレーター付き)

### 2.4 ダークモード対応

- **実装方式**: `@media (prefers-color-scheme: dark)` によるOS設定連動
- **カバー範囲**: CSS変数の全面置換 + コンポーネント個別調整 (サイドバー/ヘッダー/テーブル/ログインページ/フォーム/ボタン/ページネーション/バッジ/KPIカード)
- **手動切替**: 未実装 (トグルスイッチなし)

### 2.5 レスポンシブブレークポイント

| ブレークポイント | 対象 |
|----------------|------|
| `< 768px` | モバイル: サイドバー非表示(ハンバーガー切替)、1列レイアウト、ユーザー名非表示 |
| `768px - 1023px` | タブレット: KPIカード2列 |
| `>= 1440px` | ワイドデスクトップ: コンテンツ最大幅1600px、パディング拡大 |

### 2.6 印刷スタイル

- サイドバー/ヘッダー/ボタン/フィルター/ページネーション/フッターを非表示
- 背景色を透明化、テキスト色を黒に統一
- KPIグリッドは3列維持
- カードの改ページ回避 (`break-inside: avoid`)

---

## 3. ユーザーフロー分析

### 3.1 Login -> Dashboard -> Simulation -> Result フロー

```
[ログイン画面]
    |
    | HTMX POST /auth/login
    | (CSRF: meta tag -> X-CSRF-Token header)
    | (エラー: #login-error にHTMLスワップ)
    | (成功: HX-Redirect -> /dashboard)
    |
    v
[ダッシュボード]
    |
    | (a) クイックアクション「新規シミュレーション」クリック
    | (b) サイドバー「シミュレーション」クリック
    |     -> 通常のページ遷移 (href="/simulation/new")
    |
    v
[シミュレーション入力]
    |
    | 1. メーカー選択 -> HTMX GET でモデルリスト動的取得
    | 2. フォーム入力完了
    | 3. 「シミュレーション実行」クリック
    |    -> HTMX POST /api/v1/simulations/calculate
    |    -> #result-area に結果フラグメント注入
    |
    v
[シミュレーション結果 (インライン表示)]
    |
    | 結果フラグメント内:
    | - 8枚のサマリーカード (推奨買取価格/上限/月額リース/利回り/総額/残価/損益分岐/総合判定)
    | - 相場比較情報
    | - Chart.js 棒グラフ (月次損益推移 + 簿価ライン)
    | - 月次リーススケジュールテーブル
    | - 「新規シミュレーション」/ 「印刷」ボタン
    |
    | OR ダッシュボードの履歴テーブルからリンク
    |    -> /simulation/{id}/result (フルページ版)
```

### 3.2 Login -> Dashboard -> Market Data -> Detail フロー

```
[ダッシュボード]
    |
    | (a) クイックアクション「相場データ確認」クリック
    | (b) サイドバー「相場データ」クリック
    |     -> 通常のページ遷移 (href="/market-data")
    |
    v
[相場データ一覧]
    |
    | 1. フィルター操作 (メーカー/ボディ/年式/価格/キーワード)
    |    -> 各フィルター変更で即座にHTMX GET /market-data/table
    |    -> #data-table 内のテーブルを置換
    | 2. テーブル行クリック
    |    -> HTMX GET /market-data/{id}
    |    -> #main-content を置換 + pushUrl
    |
    v
[相場データ詳細]
    |
    | 1. 車両スペック確認
    | 2. 類似車両テーブルから別の車両詳細へ遷移
    | 3. 「この車種でシミュレーション」クリック
    |    -> /simulation/new?maker=...&model=... にパラメータ渡し
    |    -> シミュレーション画面で事前入力
    | 4. 「相場データ一覧」に戻る (戻るリンク)
```

### 3.3 エラーハンドリング

| エラー種別 | 処理 |
|-----------|------|
| **401 Unauthorized** | `app.js`: ログイン画面へリダイレクト (`window.location.href = '/auth/login'`) |
| **403 Forbidden** | トースト通知「権限がありません」(error) |
| **500+ Server Error** | トースト通知「サーバーエラーが発生しました」(error) |
| **バリデーションエラー** | `validation_error.html` パーシャルでフィールド別エラーメッセージ表示 (role="alert") |
| **ログインエラー** | `#login-error` div にHTMLスワップで直接表示 (aria-live="polite") |
| **グローバルエラー** | `#global-error` div (role="alert", aria-live="assertive") - hidden属性で初期非表示 |
| **シミュレーション結果なし** | 「結果が見つかりません」メッセージ + ダッシュボードへの戻りボタン |
| **車両データなし** | 「車両が見つかりません」メッセージ + 一覧への戻りボタン |
| **テーブル空データ** | `.empty-state` メッセージ + リセットリンク |

---

## 4. アクセシビリティ

### 4.1 ARIA属性

**実装済み**:
- `role="alert"` + `aria-live="assertive"`: グローバルエラー表示
- `role="alert"` + `aria-live="polite"`: ログインエラー、バリデーションエラー、トースト
- `aria-label="メインナビゲーション"`: サイドバーnav要素
- `aria-label="メニュー"`: ハンバーガーボタン
- `aria-label="主要指標"` / `aria-label="クイックアクション"` / `aria-label="最近のシミュレーション"`: ダッシュボードセクション
- `aria-label="フィルター"` / `aria-label="相場データ一覧"`: 相場データページ
- `aria-label="価格情報"` / `aria-label="車両スペック"` / `aria-label="類似車両"`: 詳細ページ
- `aria-label="ページナビゲーション"` / `aria-label="前のページ"` / `aria-label="次のページ"`: ページネーション
- `aria-current="page"`: アクティブページ番号
- `aria-disabled="true"`: 無効化されたページネーションリンク
- `aria-hidden="true"`: 装飾用SVGアイコン、ロゴ絵文字
- `aria-label="読み込み中"`: ローディングスピナー
- `aria-label="必須"`: フォームフィールドマクロの必須マーク
- `role="link"` + `tabindex="0"`: クリック可能なテーブル行
- `role="status"` + `aria-live="polite"`: トーストテンプレート

### 4.2 キーボードナビゲーション

**実装済み**:
- クリック可能テーブル行に `tabindex="0"` 設定 (フォーカス可能)
- `autofocus`: ログインページのメールアドレスフィールド
- 標準HTMLフォーム要素 (input/select/button) のネイティブキーボード操作

**未実装/問題点**:
- クリック可能テーブル行 (`table__row--clickable`) に `tabindex="0"` はあるが、`keydown`/`keypress` イベントハンドラがない (Enterキーで行遷移不可)
- ハンバーガーメニュー開閉時のフォーカストラップなし
- サイドバーのESCキー閉じ機能なし
- スキップナビゲーションリンクなし

### 4.3 色コントラスト

**問題点**:
- `--text-muted` (`#64748b`) on `--bg-white` (`#ffffff`): コントラスト比 約4.6:1 -> WCAG AA (4.5:1) をぎりぎり満たすが、小さいテキスト (`--text-xs` 12px) では読みにくい可能性
- `--text-light` (`#94a3b8`) on `--bg-white` (`#ffffff`): コントラスト比 約3.1:1 -> WCAG AA 不合格
- `--warning` (`#f59e0b`) のバッジテキスト on `--warning-light` (`#fef3c7`): コントラスト比が低い可能性
- ダークモードの `--text-muted` (`#94a3b8`) on `--bg-white` (`#1e293b`): コントラスト比 約4.0:1 -> WCAG AA 不合格 (小テキスト)

---

## 5. 改善提案

### 5.1 UI/UXの問題点

#### 高優先度

1. **キーボードアクセシビリティ不足**: `.table__row--clickable` に `tabindex="0"` はあるが、Enterキーハンドラがない。HTMXの `hx-get` はクリックイベントのみ対応するため、キーボードユーザーがテーブル行を遷移できない。`keydown` イベントリスナーの追加が必要。

2. **スキップナビゲーション未実装**: サイドバー後のメインコンテンツに直接ジャンプする手段がない。`<a href="#main-content" class="sr-only">コンテンツへスキップ</a>` を `<body>` 直後に追加すべき。

3. **`--text-light` のコントラスト不足**: サイドバーリンク等に使用される `#94a3b8` は白背景上でWCAG AAを満たさない。`#6b7280` 程度に暗くする必要がある。

4. **シミュレーション画面の `.form-grid` クラス未定義**: CSSに `.form-grid` の定義がなく、2列レイアウトが意図通りに機能しない可能性がある。`.form-columns` は定義済みだが使われていない。クラス名を統一すべき。

5. **相場データ一覧のHTMX遷移問題**: テーブル行クリックで `hx-target="#main-content"` + `hx-swap="innerHTML"` を使用しているが、これによりヘッダー部分も置換される可能性がある。`hx-target=".content"` またはフルページロードに変更すべき。

#### 中優先度

6. **ダークモード手動切替なし**: ユーザーがOS設定に依存せずダークモードを切り替えるUIがない。ヘッダーまたはサイドバーにトグルスイッチを追加すべき。

7. **フォントのプリロード未実装**: Inter / Noto Sans JP の `@font-face` や CDN読み込みがなく、ローカルインストールに依存。Google Fonts等からの読み込み + `<link rel="preload">` を追加すべき。

8. **装備オプションのインラインスタイル**: `simulation.html` に `<style>` タグで `.checkbox-group` / `.checkbox-label` を定義している。`style.css` に統合すべき。

9. **ページネーションの不統一**: `market_data_list.html` では簡易件数表示のみ、`vehicle_table.html` / `market_prices_table.html` ではフルページネーション。一貫性が必要。

10. **チャートのアクセシビリティ**: Chart.js のキャンバスに `aria-label` や `role="img"` がない。スクリーンリーダーユーザーにデータの代替テキストを提供すべき。

11. **コンポーネントの重複**: `navbar.html` と `base.html` のサイドバーが重複。`navbar.html` はHTMX SPA遷移対応版、`base.html` は標準版。どちらかに統一すべき。

#### 低優先度

12. **CSRFトークンの二重注入**: `login.html` ではインラインJSとhidden inputの両方でCSRFを処理。`app.js` の共通ハンドラと統一すべき。

13. **インラインスタイルの多用**: `simulation_result.html` や `simulation.html` で `style="margin-top: 24px"` 等のインラインスタイル。ユーティリティクラス (`mt-6`) の使用に置換すべき。

14. **`<hr>` のインラインスタイル**: `simulation.html` の `<hr style="margin: 32px 0">` を専用CSSクラスに変更すべき。

### 5.2 欠けている画面や機能

1. **パスワードリセット画面**: ログインページに「パスワードを忘れた方」リンク (`/auth/forgot-password`) があるが、対応テンプレートが見当たらない。

2. **シミュレーション一覧画面**: ダッシュボードの「すべて表示」リンク (`/simulations`) が存在するが、対応テンプレートがない。

3. **ユーザー設定画面**: プロフィール編集、パスワード変更等のUIがない。

4. **シミュレーション編集/再利用**: 既存シミュレーションの条件を引き継いで再計算する機能。結果画面の「条件変更して再計算」は `/simulation/new` への単純遷移で、データ引継ぎがない。

5. **PDF/CSVエクスポート**: シミュレーション結果や相場データのダウンロード機能がない (印刷ボタンはある)。

6. **通知センター**: 相場変動アラートの詳細一覧/管理画面がない (KPIカードからのリンクのみ)。

7. **管理者画面**: ユーザー管理、マスターデータ管理等の管理機能がない。

8. **404/500エラーページ**: カスタムエラーページテンプレートがない。

9. **確認ダイアログ**: ログアウトやリセット操作の確認ステップがない。

10. **相場データのグラフ表示**: `chart_fragment.html` パーシャルは存在するが、相場データ画面ではグラフ表示が統合されていない (価格推移/分布の可視化がない)。

### 5.3 モバイル対応の状態

**対応済み**:
- サイドバーのスライドイン/アウト + オーバーレイ
- ハンバーガーメニューボタン (768px未満で表示)
- グリッドレイアウトの1列化 (KPI/フォーム/フィルター)
- テーブルの横スクロール (`.table-responsive`)
- ユーザー名の非表示
- アクションボタンの縦並び化
- タッチフレンドリーなボタンサイズ (`btn--lg`)

**問題点**:
- サイドバー開閉時のbodyスクロールロックなし (背景スクロール可能)
- モバイルでのサイドバーESCキー閉じ未対応
- テーブル行のタッチターゲットサイズが44x44px未満の可能性 (パディング `12px 16px`)
- 相場データのフィルターバーがモバイルで縦に長くなりすぎる (折りたたみ/アコーディオン化が望ましい)
- `detail-grid` はモバイルで2列のまま (1列にすべき場合がある)
- チャートのaspect-ratioがモバイルで `4/3` に変更されるが、複雑なチャート (月次スケジュール) には依然として小さい可能性

---

## 付録: ファイル構成

```
app/templates/
  base.html                          -- 共通レイアウト (サイドバー + ヘッダー + メイン)
  pages/
    login.html                       -- ログイン (独立ページ)
    dashboard.html                   -- ダッシュボード
    simulation.html                  -- シミュレーション入力
    simulation_result.html           -- シミュレーション結果 (フルページ)
    market_data_list.html            -- 相場データ一覧
    market_data_detail.html          -- 相場データ詳細
  partials/
    kpi_cards.html                   -- KPIカード (HTMX partial)
    simulation_result_fragment.html  -- シミュレーション結果 (HTMX partial + Chart.js)
    vehicle_table.html               -- 車両テーブル (HTMX partial)
    market_prices_table.html         -- 相場テーブル + OOBスワップ (HTMX partial)
    model_options.html               -- 車種ドロップダウン (HTMX partial)
    market_reference.html            -- 相場参考パネル (HTMX partial)
    chart_fragment.html              -- 汎用チャート (HTMX partial + Chart.js)
    validation_error.html            -- バリデーションエラー (HTMX partial)
    toast.html                       -- トースト通知 (HTMX partial)
    recent_simulations.html          -- 最近のシミュレーション (HTMX partial)
  components/
    pagination.html                  -- ページネーション (再利用コンポーネント)
    navbar.html                      -- サイドバーナビ (代替版)
    form_field.html                  -- フォームフィールドマクロ

static/
  css/style.css                      -- 全CSSスタイル (2098行, 34セクション)
  js/app.js                          -- 共通JS (120行: CSRF, エラー処理, Chart.js, モバイルメニュー, Toast)
```
