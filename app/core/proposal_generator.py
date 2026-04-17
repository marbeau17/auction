"""Proposal document (PDF) generator for leaseback deals.

Generates professional ご説明資料 (client proposal) documents containing
integrated pricing simulation results from the CVLPOS 3-step pipeline.

Design constraints:
- Runs on Vercel (Lambda): uses lightweight HTML-to-PDF approach
- WeasyPrint for PDF when available; falls back to HTML output
- Matplotlib for NAV charts when available; graceful degradation
- Accepts both Pydantic model objects and plain dicts
"""

from __future__ import annotations

import io
import base64
import signal
import threading
from datetime import date
from pathlib import Path
from typing import Any, Optional, Union

import structlog

logger = structlog.get_logger()

# Timeout for WeasyPrint PDF generation (seconds).
# Vercel Lambda hard-limits at 10 s; we bail at 8 s to leave headroom.
WEASYPRINT_TIMEOUT_SECONDS = 8

# ---------------------------------------------------------------------------
# Optional dependency probes
# ---------------------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for server use
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from weasyprint import HTML as WeasyHTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    HAS_WEASYPRINT = False

try:
    from app.core.pdf_generator import LightweightPDFGenerator, HAS_FPDF
except ImportError:
    HAS_FPDF = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Retrieve a value from a Pydantic model or dict transparently."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _yen(value: Any) -> str:
    """Format an integer as a JPY string: ¥1,234,567."""
    try:
        return f"¥{int(value):,}"
    except (TypeError, ValueError):
        return "¥-"


def _pct(value: Any, decimals: int = 1) -> str:
    """Format a decimal as a percentage string: 5.0%."""
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "-"


def _scenario_value(residual: Any, scenario_label: str) -> int:
    """Extract a scenario residual value from the ResidualValueResult."""
    scenarios = _get(residual, "scenarios", [])
    for s in scenarios:
        label = _get(s, "label", "")
        if label == scenario_label:
            return _get(s, "residual_value", 0)
    return 0


# ---------------------------------------------------------------------------
# ProposalGenerator
# ---------------------------------------------------------------------------

class ProposalGenerator:
    """Generates leaseback proposal PDFs with pricing analysis.

    Proposal structure:
    1. Cover page (fund name, date, company)
    2. Executive summary (3 key prices)
    3. Vehicle info & deal parameters
    4. Pricing details (Step 1-3 breakdown)
    5. NAV curve chart + breakeven analysis
    6. Scenario analysis (Bull / Base / Bear)
    7. Disclaimers

    Supports both ``IntegratedPricingResult`` Pydantic models and equivalent
    plain ``dict`` representations so callers can use whichever is convenient.
    """

    # ------------------------------------------------------------------
    # NAV chart generation
    # ------------------------------------------------------------------

    def generate_nav_chart(self, nav_curve: list, lease_term: int) -> str:
        """Generate NAV curve chart as a base64-encoded PNG string.

        Returns an empty string when matplotlib is unavailable or the
        curve data is empty.
        """
        if not HAS_MATPLOTLIB or not nav_curve:
            return ""

        months = [_get(p, "month") for p in nav_curve]
        navs = [_get(p, "nav", 0) for p in nav_curve]
        book_values = [_get(p, "asset_book_value", 0) for p in nav_curve]
        cum_income = [_get(p, "cumulative_lease_income", 0) for p in nav_curve]
        cum_profit = [_get(p, "cumulative_profit", 0) for p in nav_curve]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), dpi=100)

        man_fmt = ticker.FuncFormatter(lambda x, _: f"{x:,.0f}")

        # -- Top chart: NAV / book value / cumulative income (万円) --
        ax1.plot(months, [v / 10_000 for v in navs],
                 "b-", linewidth=2, label="NAV")
        ax1.plot(months, [v / 10_000 for v in book_values],
                 "g--", linewidth=1.5, label="帳簿価額")
        ax1.plot(months, [v / 10_000 for v in cum_income],
                 "r:", linewidth=1.5, label="累積リース収入")
        ax1.set_xlabel("月")
        ax1.set_ylabel("金額（万円）")
        ax1.set_title("NAV曲線・資産価値推移")
        ax1.legend(loc="best")
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(man_fmt)

        # -- Bottom chart: cumulative profit bar chart --
        colors = ["#e53e3e" if v < 0 else "#38a169" for v in cum_profit]
        ax2.bar(months, [v / 10_000 for v in cum_profit],
                color=colors, alpha=0.7)
        ax2.axhline(y=0, color="black", linewidth=0.5)
        ax2.set_xlabel("月")
        ax2.set_ylabel("累積損益（万円）")
        ax2.set_title("累積損益推移（利益転換分析）")
        ax2.grid(True, alpha=0.3)
        ax2.yaxis.set_major_formatter(man_fmt)

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    # ------------------------------------------------------------------
    # HTML generation
    # ------------------------------------------------------------------

    def generate_html(
        self,
        pricing_result: Any,
        vehicle_info: dict,
        fund_info: dict,
        chart_b64: str = "",
    ) -> str:
        """Build the full proposal as a self-contained HTML document.

        Parameters
        ----------
        pricing_result:
            ``IntegratedPricingResult`` (Pydantic) or equivalent dict with
            keys ``acquisition``, ``residual``, ``lease``, ``nav_curve``,
            ``profit_conversion_month``, ``assessment``, ``assessment_reasons``.
        vehicle_info:
            Dict with vehicle metadata (maker, model, registration_year_month,
            mileage_km, vehicle_class, body_type, lease_term_months, ...).
        fund_info:
            Dict with fund metadata (fund_name, ...).
        chart_b64:
            Optional base64-encoded PNG chart to embed.
        """
        acq = _get(pricing_result, "acquisition", {})
        res = _get(pricing_result, "residual", {})
        lease = _get(pricing_result, "lease", {})
        fee = _get(lease, "fee_breakdown", {})

        # Scenario values
        bull_val = _scenario_value(res, "bull")
        base_val = _scenario_value(res, "base")
        bear_val = _scenario_value(res, "bear")

        # Assessment
        assessment = _get(pricing_result, "assessment", "-")
        assessment_reasons = _get(pricing_result, "assessment_reasons", [])
        profit_month = _get(pricing_result, "profit_conversion_month", "-")

        # Chart snippet
        if chart_b64:
            chart_html = (
                "<div class='chart-container'>"
                f"<img src='data:image/png;base64,{chart_b64}' alt='NAV曲線'/>"
                "</div>"
            )
        else:
            chart_html = "<p class='no-chart'>（チャート生成にはmatplotlibが必要です）</p>"

        # Assessment reasons list
        reason_items = "\n".join(
            f"<li>{r}</li>" for r in assessment_reasons
        ) if assessment_reasons else "<li>-</li>"

        # Assessment badge colour
        assess_colour_map = {"推奨": "#38a169", "要検討": "#d69e2e", "非推奨": "#e53e3e"}
        assess_colour = assess_colour_map.get(str(assessment), "#718096")

        today_str = date.today().strftime("%Y年%m月%d日")

        html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>リースバック ご説明資料</title>
<style>
    @page {{
        size: A4;
        margin: 2cm;
    }}
    * {{
        box-sizing: border-box;
    }}
    body {{
        font-family: 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Yu Gothic',
                     'Meiryo', sans-serif;
        font-size: 11pt;
        color: #2d3748;
        line-height: 1.7;
        margin: 0;
        padding: 0;
    }}

    /* ---- Cover ---- */
    .cover {{
        text-align: center;
        padding-top: 180px;
        page-break-after: always;
    }}
    .cover h1 {{
        font-size: 28pt;
        color: #1a365d;
        margin-bottom: 10px;
        letter-spacing: 0.1em;
    }}
    .cover .subtitle {{
        font-size: 14pt;
        color: #4a5568;
        margin-top: 8px;
    }}
    .cover .date {{
        font-size: 12pt;
        color: #718096;
        margin-top: 40px;
    }}
    .cover .confidential {{
        margin-top: 80px;
        font-size: 10pt;
        color: #e53e3e;
        border: 1px solid #e53e3e;
        display: inline-block;
        padding: 4px 16px;
    }}

    /* ---- Section headings ---- */
    h2 {{
        color: #1a365d;
        border-bottom: 2px solid #1a365d;
        padding-bottom: 5px;
        margin-top: 30px;
        font-size: 16pt;
    }}
    h3 {{
        color: #2d3748;
        margin-top: 20px;
        font-size: 13pt;
    }}

    /* ---- Tables ---- */
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 15px 0;
        font-size: 10.5pt;
    }}
    th, td {{
        border: 1px solid #e2e8f0;
        padding: 8px 12px;
        text-align: left;
    }}
    th {{
        background-color: #edf2f7;
        font-weight: 600;
        white-space: nowrap;
    }}

    /* ---- Price boxes ---- */
    .price-boxes {{
        display: flex;
        gap: 15px;
        justify-content: space-between;
        margin: 20px 0;
    }}
    .price-box {{
        flex: 1;
        background: #f7fafc;
        border: 2px solid #4299e1;
        border-radius: 8px;
        padding: 18px 12px;
        text-align: center;
    }}
    .price-box .label {{
        font-size: 10pt;
        color: #4a5568;
        margin-bottom: 6px;
    }}
    .price-box .value {{
        font-size: 22pt;
        color: #1a365d;
        font-weight: bold;
    }}

    /* ---- Assessment badge ---- */
    .assessment-badge {{
        display: inline-block;
        padding: 4px 18px;
        border-radius: 4px;
        color: #fff;
        font-weight: bold;
        font-size: 12pt;
    }}

    /* ---- Chart ---- */
    .chart-container {{
        text-align: center;
        margin: 20px 0;
    }}
    .chart-container img {{
        max-width: 100%;
    }}
    .no-chart {{
        color: #a0aec0;
        font-style: italic;
    }}

    /* ---- Scenario colours ---- */
    .bull {{ color: #38a169; }}
    .bear {{ color: #e53e3e; }}

    /* ---- Misc ---- */
    .page-break {{
        page-break-before: always;
    }}
    .disclaimer {{
        font-size: 9pt;
        color: #a0aec0;
        margin-top: 40px;
        border-top: 1px solid #e2e8f0;
        padding-top: 12px;
        line-height: 1.9;
    }}
    .summary-text {{
        font-size: 11pt;
        margin: 10px 0 20px 0;
    }}
    ul.reasons {{
        margin: 8px 0;
        padding-left: 24px;
    }}
    ul.reasons li {{
        margin-bottom: 4px;
    }}
</style>
</head>
<body>

<!-- ============================================================ -->
<!-- Cover Page                                                     -->
<!-- ============================================================ -->
<div class="cover">
    <h1>リースバック<br>ご説明資料</h1>
    <div class="subtitle">{fund_info.get('fund_name', 'カーチスファンド')}</div>
    <div class="subtitle" style="margin-top:16px;">
        {vehicle_info.get('maker', '')} {vehicle_info.get('model', '')}
    </div>
    <div class="date">{today_str}</div>
    <div class="date">株式会社カーチスロジテック</div>
    <div class="confidential">CONFIDENTIAL ― 秘密保持</div>
</div>

<!-- ============================================================ -->
<!-- 1. Executive Summary                                          -->
<!-- ============================================================ -->
<h2>1. エグゼクティブサマリー</h2>
<p class="summary-text">
    本資料は、対象車両のリースバック取引における適正価格シミュレーション結果を
    まとめたものです。3段階プライシングパイプライン（適正買取価格 → 残価算定 →
    月額リース料算出）に基づき分析しております。
</p>

<div class="price-boxes">
    <div class="price-box">
        <div class="label">適正買取価格</div>
        <div class="value">{_yen(_get(acq, 'recommended_price', 0))}</div>
    </div>
    <div class="price-box">
        <div class="label">適正残価（Base）</div>
        <div class="value">{_yen(base_val)}</div>
    </div>
    <div class="price-box">
        <div class="label">月額リース料</div>
        <div class="value">{_yen(_get(lease, 'monthly_lease_fee', 0))}</div>
    </div>
</div>

<p>
    総合判定:
    <span class="assessment-badge" style="background:{assess_colour};">
        {assessment}
    </span>
</p>
<ul class="reasons">
{reason_items}
</ul>

<!-- ============================================================ -->
<!-- 2. Vehicle Info                                                -->
<!-- ============================================================ -->
<div class="page-break"></div>
<h2>2. 対象車両情報</h2>
<table>
    <tr>
        <th>メーカー</th><td>{vehicle_info.get('maker', '-')}</td>
        <th>車種</th><td>{vehicle_info.get('model', '-')}</td>
    </tr>
    <tr>
        <th>型式</th><td>{vehicle_info.get('model_code', '-')}</td>
        <th>初年度登録</th><td>{vehicle_info.get('registration_year_month', '-')}</td>
    </tr>
    <tr>
        <th>走行距離</th><td>{vehicle_info.get('mileage_km', 0):,} km</td>
        <th>車両クラス</th><td>{vehicle_info.get('vehicle_class', '-')}</td>
    </tr>
    <tr>
        <th>ボディタイプ</th><td>{vehicle_info.get('body_type', '-')}</td>
        <th>積載量</th><td>{vehicle_info.get('payload_ton', '-')} t</td>
    </tr>
    <tr>
        <th>リース期間</th><td>{vehicle_info.get('lease_term_months', '-')} ヶ月</td>
        <th>架装・オプション評価額</th><td>{_yen(vehicle_info.get('body_option_value', 0))}</td>
    </tr>
</table>

<!-- ============================================================ -->
<!-- 3. Pricing Details                                            -->
<!-- ============================================================ -->
<h2>3. プライシング詳細</h2>

<h3>Step 1: 適正買取価格</h3>
<table>
    <tr><th>市場相場中央値</th><td>{_yen(_get(acq, 'market_median', 0))}</td></tr>
    <tr><th>市場サンプル数</th><td>{_get(acq, 'sample_count', 0)} 件</td></tr>
    <tr><th>信頼度</th><td>{_get(acq, 'confidence', '-')}</td></tr>
    <tr><th>トレンド係数</th><td>{_get(acq, 'trend_factor', 1.0):.4f}</td></tr>
    <tr><th>トレンド方向</th><td>{_get(acq, 'trend_direction', '-')}</td></tr>
    <tr><th>安全マージン率</th><td>{_pct(_get(acq, 'safety_margin_rate', 0))}</td></tr>
    <tr><th>架装・オプション加算</th><td>{_yen(_get(acq, 'body_option_value', 0))}</td></tr>
    <tr>
        <th>推奨買取価格</th>
        <td><strong>{_yen(_get(acq, 'recommended_price', 0))}</strong></td>
    </tr>
    <tr><th>上限買取価格</th><td>{_yen(_get(acq, 'max_price', 0))}</td></tr>
    <tr>
        <th>許容価格帯</th>
        <td>{_yen(_get(acq, 'price_range_low', 0))} 〜 {_yen(_get(acq, 'price_range_high', 0))}</td>
    </tr>
</table>

<h3>Step 2: 適正残価（エグジット価格）</h3>
<table>
    <tr><th>償却方法</th><td>{_get(res, 'depreciation_method', '-')}</td></tr>
    <tr><th>法定耐用年数</th><td>{_get(res, 'useful_life_years', '-')} 年</td></tr>
    <tr><th>経過年数</th><td>{_get(res, 'elapsed_years', '-')} 年</td></tr>
    <tr><th>残存耐用年数</th><td>{_get(res, 'remaining_useful_life_years', '-')} 年</td></tr>
    <tr><th>ボディ残存率</th><td>{_pct(_get(res, 'body_retention_rate', 0))}</td></tr>
    <tr><th>走行距離調整係数</th><td>{_get(res, 'mileage_adjustment', 1.0)}</td></tr>
</table>

<table>
    <tr><th>シナリオ</th><th>残価</th><th>乗数</th></tr>
    <tr class="bull">
        <td>Bull（楽観）</td>
        <td>{_yen(bull_val)}</td>
        <td>×1.15</td>
    </tr>
    <tr>
        <td><strong>Base（基準）</strong></td>
        <td><strong>{_yen(base_val)}</strong></td>
        <td>×1.00</td>
    </tr>
    <tr class="bear">
        <td>Bear（悲観）</td>
        <td>{_yen(bear_val)}</td>
        <td>×0.85</td>
    </tr>
</table>

<!-- ============================================================ -->
<!-- Step 3: Lease Fee Breakdown                                   -->
<!-- ============================================================ -->
<div class="page-break"></div>
<h3>Step 3: 月額リース料内訳</h3>
<table>
    <tr><th>項目</th><th>月額（円）</th></tr>
    <tr><td>減価償却費</td><td>{_yen(_get(fee, 'depreciation_portion', 0))}</td></tr>
    <tr><td>投資家配当</td><td>{_yen(_get(fee, 'investor_dividend_portion', 0))}</td></tr>
    <tr><td>AM報酬</td><td>{_yen(_get(fee, 'am_fee_portion', 0))}</td></tr>
    <tr><td>私募取扱報酬</td><td>{_yen(_get(fee, 'placement_fee_portion', 0))}</td></tr>
    <tr><td>会計事務委託料</td><td>{_yen(_get(fee, 'accounting_fee_portion', 0))}</td></tr>
    <tr><td>オペレーターマージン</td><td>{_yen(_get(fee, 'operator_margin_portion', 0))}</td></tr>
    <tr style="font-weight:bold; background:#edf2f7;">
        <td>合計月額リース料（税抜）</td>
        <td>{_yen(_get(fee, 'total_monthly_fee', _get(lease, 'monthly_lease_fee', 0)))}</td>
    </tr>
    <tr>
        <td>合計月額リース料（税込 10%）</td>
        <td>{_yen(_get(lease, 'monthly_lease_fee_tax_incl', 0))}</td>
    </tr>
    <tr><td>年間リース料（税抜）</td><td>{_yen(_get(lease, 'annual_lease_fee', 0))}</td></tr>
    <tr><td>総額リース料（税抜）</td><td>{_yen(_get(lease, 'total_lease_fee', 0))}</td></tr>
</table>

<table>
    <tr><th>実効利回り（年率）</th><td>{_pct(_get(lease, 'effective_yield_rate', 0), 2)}</td></tr>
    <tr><th>損益分岐月</th><td>第 {_get(lease, 'breakeven_month', '-')} ヶ月</td></tr>
</table>

<!-- ============================================================ -->
<!-- 4. NAV Curve & Breakeven                                      -->
<!-- ============================================================ -->
<div class="page-break"></div>
<h2>4. NAV曲線・利益転換分析</h2>
<p>
    利益転換月: <strong>第{profit_month}ヶ月</strong>
    ― 累積損益が黒字に転換する月を示します。リース期間に対する比率が低いほど
    投資安全性が高いと評価されます。
</p>
{chart_html}

<!-- ============================================================ -->
<!-- 5. Disclaimers                                                -->
<!-- ============================================================ -->
<div class="page-break"></div>
<h2>5. 注意事項・免責</h2>
<div class="disclaimer">
<p>・本資料に記載された価格・利回り等は、シミュレーション結果に基づく参考値であり、
将来の実績を保証するものではありません。</p>
<p>・市場環境、車両の状態、経済状況等により実際の価格は変動する可能性があります。</p>
<p>・投資にはリスクが伴います。投資判断はご自身の責任において行ってください。</p>
<p>・市場データはオートオークション落札実績及び公開市場情報に基づいています。
データの正確性について保証するものではありません。</p>
<p>・本資料の無断複写・転載を禁じます。</p>
<p style="margin-top:24px; color:#718096;">
    作成: CVLPOS（商用車リースバック価格最適化システム）<br>
    作成日: {today_str}
</p>
</div>

</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # PDF generation
    # ------------------------------------------------------------------

    def generate_pdf(
        self,
        pricing_result: Any,
        vehicle_info: dict,
        fund_info: dict,
    ) -> bytes:
        """Generate a proposal as PDF bytes.

        Strategy (ordered by preference):
        1. WeasyPrint with an 8-second timeout (full-fidelity PDF).
        2. fpdf2 lightweight fallback (no native deps, fast).
        3. UTF-8-encoded HTML bytes (last resort).

        Returns
        -------
        bytes
            PDF content (preferred) or HTML content (last-resort fallback).
        """
        chart_b64 = ""
        nav_curve = _get(pricing_result, "nav_curve")
        if HAS_MATPLOTLIB and nav_curve:
            chart_b64 = self.generate_nav_chart(
                nav_curve,
                vehicle_info.get("lease_term_months", 36),
            )

        html_content = self.generate_html(
            pricing_result, vehicle_info, fund_info, chart_b64,
        )

        # --- Attempt 1: WeasyPrint with timeout ---
        if HAS_WEASYPRINT:
            pdf_bytes = self._weasyprint_with_timeout(html_content)
            if pdf_bytes is not None:
                logger.info("proposal_pdf_generated", method="weasyprint")
                return pdf_bytes
            # WeasyPrint timed out or errored – fall through to fpdf2

        # --- Attempt 2: fpdf2 lightweight fallback ---
        if HAS_FPDF:
            try:
                return self.generate_lightweight_pdf(
                    pricing_result, vehicle_info, fund_info,
                )
            except Exception:
                logger.exception("fpdf2_fallback_failed")

        # --- Attempt 3: raw HTML ---
        logger.warning(
            "pdf_generation_unavailable",
            msg="Returning HTML instead of PDF — no PDF backend succeeded",
        )
        return html_content.encode("utf-8")

    # ------------------------------------------------------------------
    # WeasyPrint with timeout
    # ------------------------------------------------------------------

    @staticmethod
    def _weasyprint_with_timeout(html_content: str) -> bytes | None:
        """Run WeasyPrint in a thread with a timeout.

        Returns PDF bytes on success, or ``None`` if the generation
        exceeds ``WEASYPRINT_TIMEOUT_SECONDS`` or raises an error.
        """
        result: list[bytes | None] = [None]
        error: list[Exception | None] = [None]

        def _render() -> None:
            try:
                result[0] = WeasyHTML(string=html_content).write_pdf()
            except Exception as exc:  # noqa: BLE001
                error[0] = exc

        thread = threading.Thread(target=_render, daemon=True)
        thread.start()
        thread.join(timeout=WEASYPRINT_TIMEOUT_SECONDS)

        if thread.is_alive():
            logger.warning(
                "weasyprint_timeout",
                timeout_seconds=WEASYPRINT_TIMEOUT_SECONDS,
                msg="WeasyPrint exceeded timeout; falling back to fpdf2",
            )
            return None

        if error[0] is not None:
            logger.warning(
                "weasyprint_error",
                error=str(error[0]),
                msg="WeasyPrint raised an error; falling back to fpdf2",
            )
            return None

        return result[0]

    # ------------------------------------------------------------------
    # Lightweight PDF via fpdf2
    # ------------------------------------------------------------------

    def generate_lightweight_pdf(
        self,
        pricing_result: Any,
        vehicle_info: dict,
        fund_info: dict,
    ) -> bytes:
        """Generate a proposal PDF using fpdf2 (lightweight).

        This produces a condensed but professional PDF without requiring
        any native C libraries.  Japanese font support is best-effort:
        a CJK font is loaded if available on the system.

        Raises ``RuntimeError`` if fpdf2 is not installed.
        """
        # Normalise to dict if Pydantic model
        if not isinstance(pricing_result, dict):
            try:
                pricing_result = pricing_result.model_dump()
            except AttributeError:
                pricing_result = dict(pricing_result)

        gen = LightweightPDFGenerator()
        return gen.generate_proposal_summary_pdf(
            pricing_result, vehicle_info, fund_info,
        )

    # ------------------------------------------------------------------
    # HTML preview (for browser / iframe display)
    # ------------------------------------------------------------------

    def generate_html_preview(
        self,
        pricing_result: Any,
        vehicle_info: dict,
        fund_info: dict,
    ) -> str:
        """Generate an HTML string suitable for browser preview.

        Identical to the PDF content but returned as a string rather than
        bytes, so it can be served directly as ``text/html``.
        """
        chart_b64 = ""
        nav_curve = _get(pricing_result, "nav_curve")
        if HAS_MATPLOTLIB and nav_curve:
            chart_b64 = self.generate_nav_chart(
                nav_curve,
                vehicle_info.get("lease_term_months", 36),
            )

        return self.generate_html(
            pricing_result, vehicle_info, fund_info, chart_b64,
        )
