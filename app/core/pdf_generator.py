"""Lightweight PDF generator using fpdf2 for Vercel Lambda compatibility.

WeasyPrint requires system-level libraries (Cairo, Pango, etc.) that may
exceed Vercel's 50 MB function size limit or 10-second execution budget.
This module provides a pure-Python fallback using fpdf2 (~2 MB, no native
deps) that generates acceptable PDFs for invoices and proposal summaries.

Japanese text support
---------------------
fpdf2 ships with built-in Unicode support.  We attempt to load a CJK font
(NotoSansCJKjp) if available; otherwise we fall back to the built-in
Helvetica and replace characters that cannot be rendered.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

import structlog

logger = structlog.get_logger()

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


def _yen(value: Any) -> str:
    """Format an integer as a JPY string."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any, decimals: int = 1) -> str:
    """Format a decimal as a percentage string."""
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "-"


# ---------------------------------------------------------------------------
# Font helper
# ---------------------------------------------------------------------------

_FONT_SEARCH_PATHS = [
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/NotoSansCJKjp-Regular.otf",
    # Linux / Vercel
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
    # Bundled (if the project ships a font)
    "fonts/NotoSansJP-Regular.ttf",
]


def _register_japanese_font(pdf: FPDF) -> str:
    """Try to register a Japanese-capable font; return the family name.

    Returns ``"Helvetica"`` when no CJK font is found so the PDF is still
    generated (with degraded glyph coverage).
    """
    import os

    for path in _FONT_SEARCH_PATHS:
        if os.path.isfile(path):
            try:
                pdf.add_font("jpfont", "", path, uni=True)
                # fpdf2 needs each style registered separately. Register the
                # same TTF as the bold variant so callers can use set_font(
                # family, "B", ...) without hitting FPDFException. For true
                # bold we'd register a dedicated bold TTF, but most CJK
                # system fonts ship only a single weight.
                try:
                    pdf.add_font("jpfont", "B", path, uni=True)
                except Exception:  # noqa: BLE001
                    pass
                return "jpfont"
            except Exception:  # noqa: BLE001
                continue

    logger.warning("cjk_font_not_found", msg="Falling back to Helvetica")
    return "Helvetica"


# ---------------------------------------------------------------------------
# LightweightPDFGenerator
# ---------------------------------------------------------------------------


class LightweightPDFGenerator:
    """Pure-Python PDF generator backed by fpdf2.

    Designed to stay well within Vercel Lambda limits:
    - No native C dependencies
    - Package size ~2 MB
    - Generation time <2 seconds for typical documents
    """

    def __init__(self) -> None:
        if not HAS_FPDF:
            raise RuntimeError(
                "fpdf2 is not installed. Run: pip install fpdf2"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_pdf(orientation: str = "P") -> tuple[FPDF, str]:
        """Create a fresh FPDF instance with Japanese font registered."""
        pdf = FPDF(orientation=orientation, unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=20)
        font_family = _register_japanese_font(pdf)
        return pdf, font_family

    @staticmethod
    def _section_header(pdf: FPDF, font: str, text: str) -> None:
        pdf.set_font(font, "B", 14)
        pdf.set_text_color(26, 54, 93)  # #1a365d
        pdf.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
        # underline
        pdf.set_draw_color(26, 54, 93)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)
        pdf.set_text_color(0, 0, 0)

    @staticmethod
    def _kv_row(pdf: FPDF, font: str, label: str, value: str) -> None:
        pdf.set_font(font, "B", 10)
        pdf.cell(55, 7, label, border=1)
        pdf.set_font(font, "", 10)
        pdf.cell(0, 7, value, border=1, new_x="LMARGIN", new_y="NEXT")

    # ------------------------------------------------------------------
    # Public: Invoice PDF
    # ------------------------------------------------------------------

    def generate_invoice_pdf(self, invoice_data: dict) -> bytes:
        """Generate an invoice PDF using fpdf2 (lightweight).

        Parameters
        ----------
        invoice_data:
            Dict with keys: invoice_number, created_at, billing_period_start,
            billing_period_end, due_date, line_items, subtotal, tax_rate,
            tax_amount, total_amount, notes.

        Returns
        -------
        bytes
            Raw PDF content.
        """
        pdf, font = self._new_pdf()
        pdf.add_page()

        # -- Title --
        pdf.set_font(font, "B", 22)
        pdf.set_text_color(26, 86, 219)  # #1a56db
        pdf.cell(0, 14, "請 求 書", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "INVOICE", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # -- Issuer info --
        pdf.set_font(font, "B", 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "CVLPOS株式会社", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, "", 9)
        pdf.set_text_color(80, 80, 80)
        for line in [
            "〒100-0001 東京都千代田区千代田1-1-1",
            "TEL: 03-XXXX-XXXX",
            "登録番号: T1234567890123",
        ]:
            pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

        # -- Meta info --
        pdf.set_text_color(0, 0, 0)
        self._kv_row(pdf, font, "請求番号", str(invoice_data.get("invoice_number", "")))
        created = str(invoice_data.get("created_at", ""))[:10]
        self._kv_row(pdf, font, "請求日", created)
        period = (
            f"{invoice_data.get('billing_period_start', '')} 〜 "
            f"{invoice_data.get('billing_period_end', '')}"
        )
        self._kv_row(pdf, font, "請求期間", period)
        self._kv_row(pdf, font, "支払期日", str(invoice_data.get("due_date", "")))
        pdf.ln(6)

        # -- Line items table --
        col_widths = [12, 70, 20, 35, 35]
        headers = ["No.", "摘要", "数量", "単価", "金額"]

        pdf.set_font(font, "B", 9)
        pdf.set_fill_color(26, 86, 219)
        pdf.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 8, h, border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_text_color(0, 0, 0)
        pdf.set_font(font, "", 9)
        for idx, item in enumerate(invoice_data.get("line_items", []), start=1):
            pdf.cell(col_widths[0], 7, str(idx), border=1, align="C")
            pdf.cell(col_widths[1], 7, str(item.get("description", "")), border=1)
            pdf.cell(col_widths[2], 7, str(item.get("quantity", 1)), border=1, align="R")
            pdf.cell(col_widths[3], 7, f"Y{_yen(item.get('unit_price', 0))}", border=1, align="R")
            pdf.cell(col_widths[4], 7, f"Y{_yen(item.get('amount', 0))}", border=1, align="R")
            pdf.ln()

        pdf.ln(4)

        # -- Totals --
        x_offset = pdf.w - pdf.r_margin - 80
        pdf.set_font(font, "", 10)
        for label, key in [("小計", "subtotal"), ("消費税", "tax_amount")]:
            pdf.set_x(x_offset)
            pdf.cell(40, 7, f"{label}:", align="R")
            pdf.cell(40, 7, f"Y{_yen(invoice_data.get(key, 0))}", align="R",
                     new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(font, "B", 13)
        pdf.set_x(x_offset)
        pdf.cell(40, 10, "合計金額:", align="R")
        pdf.cell(40, 10, f"Y{_yen(invoice_data.get('total_amount', 0))}", align="R",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

        # -- Payment info --
        pdf.set_font(font, "B", 10)
        pdf.cell(0, 7, "お振込先", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, "", 9)
        for line in [
            "三菱UFJ銀行 丸の内支店（001）",
            "普通預金 1234567",
            "口座名義: シーブイエルポス（カ",
        ]:
            pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

        # -- Notes --
        notes = invoice_data.get("notes")
        if notes:
            pdf.ln(6)
            pdf.set_font(font, "B", 9)
            pdf.cell(0, 6, "備考:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(font, "", 9)
            pdf.multi_cell(0, 5, str(notes))

        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)
        logger.info("invoice_pdf_generated", method="fpdf2")
        return buf.read()

    # ------------------------------------------------------------------
    # Public: Proposal summary PDF
    # ------------------------------------------------------------------

    def generate_proposal_summary_pdf(
        self,
        pricing_result: dict,
        vehicle_info: dict,
        fund_info: dict | None = None,
    ) -> bytes:
        """Generate a simplified proposal summary PDF.

        This is a condensed version of the full WeasyPrint proposal,
        containing the key pricing data without the NAV chart.

        Returns
        -------
        bytes
            Raw PDF content.
        """
        fund_info = fund_info or {}
        pdf, font = self._new_pdf()

        acq = pricing_result.get("acquisition", {})
        res = pricing_result.get("residual", {})
        lease = pricing_result.get("lease", {})
        fee = lease.get("fee_breakdown", {}) if isinstance(lease, dict) else {}

        # -- Cover page --
        pdf.add_page()
        pdf.ln(60)
        pdf.set_font(font, "B", 26)
        pdf.set_text_color(26, 54, 93)
        pdf.cell(0, 14, "リースバック", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 14, "ご説明資料", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)
        pdf.set_font(font, "", 13)
        pdf.set_text_color(74, 85, 104)
        pdf.cell(0, 8, fund_info.get("fund_name", "カーチスファンド"),
                 align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(
            0, 8,
            f"{vehicle_info.get('maker', '')} {vehicle_info.get('model', '')}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(12)
        pdf.set_font(font, "", 11)
        pdf.set_text_color(113, 128, 150)
        pdf.cell(0, 7, date.today().strftime("%Y年%m月%d日"),
                 align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "株式会社カーチスロジテック",
                 align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(20)
        pdf.set_font(font, "", 9)
        pdf.set_text_color(229, 62, 62)
        pdf.cell(0, 7, "CONFIDENTIAL - 秘密保持", align="C",
                 new_x="LMARGIN", new_y="NEXT")

        # -- Executive summary page --
        pdf.add_page()
        self._section_header(pdf, font, "1. エグゼクティブサマリー")

        pdf.set_font(font, "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.multi_cell(0, 6, (
            "本資料は、対象車両のリースバック取引における適正価格シミュレーション"
            "結果をまとめたものです。"
        ))
        pdf.ln(6)

        # Key prices as a table
        prices = [
            ("適正買取価格", f"Y{_yen(acq.get('recommended_price', 0))}"),
            ("適正残価（Base）", f"Y{_yen(self._base_val(res))}"),
            ("月額リース料", f"Y{_yen(lease.get('monthly_lease_fee', 0))}"),
        ]
        pdf.set_font(font, "B", 11)
        for label, val in prices:
            pdf.cell(60, 10, label, border=1)
            pdf.set_font(font, "B", 13)
            pdf.cell(0, 10, val, border=1, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(font, "B", 11)
        pdf.ln(4)

        # Assessment
        assessment = pricing_result.get("assessment", "-")
        pdf.set_font(font, "B", 11)
        pdf.cell(30, 8, "総合判定: ")
        pdf.set_font(font, "B", 13)
        pdf.cell(0, 8, str(assessment), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        reasons = pricing_result.get("assessment_reasons", [])
        if reasons:
            pdf.set_font(font, "", 9)
            for r in reasons:
                pdf.cell(6, 5, "-")
                pdf.cell(0, 5, str(r), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

        # -- Vehicle info --
        self._section_header(pdf, font, "2. 対象車両情報")
        vehicle_fields = [
            ("メーカー", vehicle_info.get("maker", "-")),
            ("車種", vehicle_info.get("model", "-")),
            ("初年度登録", str(vehicle_info.get("registration_year_month", "-"))),
            ("走行距離", f"{vehicle_info.get('mileage_km', 0):,} km"),
            ("車両クラス", vehicle_info.get("vehicle_class", "-")),
            ("ボディタイプ", vehicle_info.get("body_type", "-")),
            ("リース期間", f"{vehicle_info.get('lease_term_months', '-')} ヶ月"),
        ]
        for label, val in vehicle_fields:
            self._kv_row(pdf, font, label, str(val))
        pdf.ln(6)

        # -- Pricing details --
        pdf.add_page()
        self._section_header(pdf, font, "3. プライシング詳細")

        pdf.set_font(font, "B", 11)
        pdf.cell(0, 8, "Step 1: 適正買取価格", new_x="LMARGIN", new_y="NEXT")
        step1_fields = [
            ("市場相場中央値", f"Y{_yen(acq.get('market_median', 0))}"),
            ("市場サンプル数", f"{acq.get('sample_count', 0)} 件"),
            ("信頼度", str(acq.get("confidence", "-"))),
            ("推奨買取価格", f"Y{_yen(acq.get('recommended_price', 0))}"),
            ("上限買取価格", f"Y{_yen(acq.get('max_price', 0))}"),
        ]
        for label, val in step1_fields:
            self._kv_row(pdf, font, label, val)
        pdf.ln(4)

        pdf.set_font(font, "B", 11)
        pdf.cell(0, 8, "Step 2: 適正残価", new_x="LMARGIN", new_y="NEXT")
        scenarios = res.get("scenarios", [])
        for s in scenarios:
            lbl = s.get("label", "")
            self._kv_row(pdf, font, f"残価（{lbl}）", f"Y{_yen(s.get('residual_value', 0))}")
        pdf.ln(4)

        pdf.set_font(font, "B", 11)
        pdf.cell(0, 8, "Step 3: 月額リース料内訳", new_x="LMARGIN", new_y="NEXT")
        fee_fields = [
            ("減価償却費", fee.get("depreciation_portion", 0)),
            ("投資家配当", fee.get("investor_dividend_portion", 0)),
            ("AM報酬", fee.get("am_fee_portion", 0)),
            ("私募取扱報酬", fee.get("placement_fee_portion", 0)),
            ("会計事務委託料", fee.get("accounting_fee_portion", 0)),
            ("オペレーターマージン", fee.get("operator_margin_portion", 0)),
        ]
        for label, val in fee_fields:
            self._kv_row(pdf, font, label, f"Y{_yen(val)}")

        pdf.set_font(font, "B", 10)
        pdf.cell(55, 8, "合計月額（税抜）", border=1, fill=False)
        total_fee = fee.get("total_monthly_fee", lease.get("monthly_lease_fee", 0))
        pdf.cell(0, 8, f"Y{_yen(total_fee)}", border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        self._kv_row(pdf, font, "実効利回り（年率）", _pct(lease.get("effective_yield_rate", 0), 2))
        self._kv_row(pdf, font, "損益分岐月", f"第 {lease.get('breakeven_month', '-')} ヶ月")
        self._kv_row(
            pdf, font, "利益転換月",
            f"第 {pricing_result.get('profit_conversion_month', '-')} ヶ月",
        )

        # -- Disclaimers --
        pdf.add_page()
        self._section_header(pdf, font, "4. 注意事項・免責")
        pdf.set_font(font, "", 8)
        pdf.set_text_color(130, 130, 130)
        disclaimers = [
            "・本資料に記載された価格・利回り等は、シミュレーション結果に基づく参考値であり、将来の実績を保証するものではありません。",
            "・市場環境、車両の状態、経済状況等により実際の価格は変動する可能性があります。",
            "・投資にはリスクが伴います。投資判断はご自身の責任において行ってください。",
            "・市場データはオートオークション落札実績及び公開市場情報に基づいています。",
            "・本資料の無断複写・転載を禁じます。",
        ]
        for d in disclaimers:
            pdf.multi_cell(0, 5, d)
            pdf.ln(2)

        pdf.ln(8)
        pdf.set_font(font, "", 9)
        pdf.cell(0, 6, f"作成: CVLPOS（商用車リースバック価格最適化システム）",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"作成日: {date.today().strftime('%Y年%m月%d日')}",
                 new_x="LMARGIN", new_y="NEXT")

        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)
        logger.info("proposal_pdf_generated", method="fpdf2")
        return buf.read()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _base_val(residual: dict) -> int:
        """Extract the base scenario residual value."""
        for s in residual.get("scenarios", []):
            if s.get("label") == "base":
                return s.get("residual_value", 0)
        return 0
