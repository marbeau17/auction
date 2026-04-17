"""Monthly investor-report PDF generator (INV-004).

Builds a 5-page investor statement from live fund / lease / NAV data and
renders it with :class:`app.core.pdf_generator.LightweightPDFGenerator`
(fpdf2 under the hood — Vercel-Lambda friendly).

Page layout
-----------
1. Cover — fund name + reporting period
2. NAV summary + trend (text table of the last 12 months)
3. Dividend history (monthly distributions, paid vs scheduled)
4. Portfolio snapshot — vehicle count, total acquisition / market value
5. Risk flags & notes

The generator intentionally depends on a Supabase client (duck-typed so unit
tests can pass a ``FakeClient``) — ``generate(fund_id, report_month)`` queries:

* ``funds`` — fund header
* ``vehicle_nav_history`` — per-fund NAV snapshots (latest month + last 12)
* ``fund_distributions`` — dividend history and next-month scheduled amount
* ``lease_payments`` / ``invoices`` — overdue detection for risk flags
* ``simulations`` — (optional) target yield
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any, Optional
from uuid import UUID

import structlog

from app.core.pdf_generator import LightweightPDFGenerator

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _yen(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _month_str(d: date | str | None) -> str:
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return str(d)
    if isinstance(d, date):
        return d.strftime("%Y-%m")
    return "-"


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _month_bounds(d: date) -> tuple[date, date]:
    start = _first_of_month(d)
    if start.month == 12:
        end_next = start.replace(year=start.year + 1, month=1)
    else:
        end_next = start.replace(month=start.month + 1)
    return start, end_next - timedelta(days=1)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class InvestorReportGenerator:
    """Produce the monthly investor PDF for a single fund."""

    def __init__(self, client: Any, pdf_generator: Optional[LightweightPDFGenerator] = None) -> None:
        self._client = client
        self._pdf = pdf_generator or LightweightPDFGenerator()

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def generate(self, fund_id: UUID | str, report_month: date) -> tuple[bytes, dict[str, Any]]:
        """Build the report PDF and return (pdf_bytes, metrics_dict).

        The metrics dict carries the headline numbers we persist on the
        ``investor_reports`` row (nav_total / dividend_paid / etc.) so the
        caller can write the DB record in a single pass.
        """
        report_month = _first_of_month(report_month)
        fund = self._fetch_fund(fund_id)
        nav_rows = self._fetch_nav_history(fund_id, report_month)
        dividends = self._fetch_dividends(fund_id, report_month)
        portfolio = self._fetch_portfolio_snapshot(fund_id, report_month)
        risk_flags = self._evaluate_risk(fund_id, report_month, nav_rows, portfolio)

        nav_total = int(sum((r.get("nav") or 0) for r in nav_rows if _same_month(r.get("recording_date"), report_month)))
        dividend_paid = int(sum(d.get("distribution_amount") or 0 for d in dividends["paid"]))
        dividend_scheduled = int(sum(d.get("distribution_amount") or 0 for d in dividends["scheduled"]))

        pdf_bytes = self._render_pdf(
            fund=fund,
            report_month=report_month,
            nav_rows=nav_rows,
            dividends=dividends,
            portfolio=portfolio,
            risk_flags=risk_flags,
            nav_total=nav_total,
            dividend_paid=dividend_paid,
            dividend_scheduled=dividend_scheduled,
        )

        metrics = {
            "nav_total": nav_total,
            "dividend_paid": dividend_paid,
            "dividend_scheduled": dividend_scheduled,
            "risk_flags": risk_flags,
        }
        logger.info(
            "investor_report_generated",
            fund_id=str(fund_id),
            report_month=report_month.isoformat(),
            nav_total=nav_total,
            dividend_paid=dividend_paid,
            dividend_scheduled=dividend_scheduled,
            risk_flag_count=len(risk_flags),
        )
        return pdf_bytes, metrics

    # ------------------------------------------------------------------
    # Data access (Supabase client duck-typed for unit tests)
    # ------------------------------------------------------------------

    def _fetch_fund(self, fund_id: UUID | str) -> dict[str, Any]:
        try:
            resp = (
                self._client.table("funds")
                .select("*")
                .eq("id", str(fund_id))
                .maybe_single()
                .execute()
            )
            return dict(resp.data or {}) or {"id": str(fund_id), "fund_name": "(unknown fund)"}
        except Exception:
            logger.exception("investor_report_fund_fetch_failed", fund_id=str(fund_id))
            return {"id": str(fund_id), "fund_name": "(unknown fund)"}

    def _fetch_nav_history(self, fund_id: UUID | str, report_month: date) -> list[dict[str, Any]]:
        """Fetch the last 12 monthly NAV snapshots for the fund, newest first."""
        try:
            resp = (
                self._client.table("vehicle_nav_history")
                .select("*")
                .eq("fund_id", str(fund_id))
                .order("recording_date", desc=True)
                .limit(500)
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.exception("investor_report_nav_fetch_failed", fund_id=str(fund_id))
            return []

    def _fetch_dividends(self, fund_id: UUID | str, report_month: date) -> dict[str, list[dict[str, Any]]]:
        """Return {'paid': [...12m history], 'scheduled': [...next month]}."""
        paid: list[dict[str, Any]] = []
        scheduled: list[dict[str, Any]] = []
        try:
            resp = (
                self._client.table("fund_distributions")
                .select("*")
                .eq("fund_id", str(fund_id))
                .order("distribution_date", desc=True)
                .execute()
            )
            rows = resp.data or []
            # Next month = report_month + 1 month
            if report_month.month == 12:
                next_month = report_month.replace(year=report_month.year + 1, month=1)
            else:
                next_month = report_month.replace(month=report_month.month + 1)
            for row in rows:
                dd = row.get("distribution_date")
                dd_date = _parse_date(dd)
                if dd_date is None:
                    continue
                if dd_date >= next_month and dd_date < _add_month(next_month):
                    scheduled.append(row)
                elif dd_date <= report_month.replace(day=28):
                    paid.append(row)
        except Exception:
            logger.exception("investor_report_dividends_fetch_failed", fund_id=str(fund_id))
        return {"paid": paid, "scheduled": scheduled}

    def _fetch_portfolio_snapshot(
        self, fund_id: UUID | str, report_month: date
    ) -> dict[str, Any]:
        """Aggregate vehicle counts + book/market values for the fund."""
        try:
            resp = (
                self._client.table("secured_asset_blocks")
                .select("*")
                .eq("fund_id", str(fund_id))
                .execute()
            )
            sabs = resp.data or []
            active = [s for s in sabs if s.get("status") in ("held", "leased")]
            total_acq = sum(int(s.get("acquisition_price") or 0) for s in active)
            total_val = sum(int(s.get("adjusted_valuation") or s.get("b2b_wholesale_valuation") or 0) for s in active)
            return {
                "vehicle_count": len(active),
                "total_acquisition": total_acq,
                "total_market_value": total_val,
                "items": active,
            }
        except Exception:
            logger.exception("investor_report_portfolio_fetch_failed", fund_id=str(fund_id))
            return {"vehicle_count": 0, "total_acquisition": 0, "total_market_value": 0, "items": []}

    # ------------------------------------------------------------------
    # Risk evaluation
    # ------------------------------------------------------------------

    def _evaluate_risk(
        self,
        fund_id: UUID | str,
        report_month: date,
        nav_rows: list[dict[str, Any]],
        portfolio: dict[str, Any],
    ) -> list[dict[str, Any]]:
        flags: list[dict[str, Any]] = []

        # NFAV floor (spec §1.3) — NAV this month vs initial fundraise
        month_rows = [r for r in nav_rows if _same_month(r.get("recording_date"), report_month)]
        nav_total = sum(int(r.get("nav") or 0) for r in month_rows)
        acq_total = int(portfolio.get("total_acquisition") or 0)
        if acq_total > 0:
            nfav_ratio = nav_total / acq_total
            if nfav_ratio < 0.60:
                flags.append({
                    "code": "nfav_below_60",
                    "severity": "critical",
                    "message": f"NFAV {nfav_ratio*100:.1f}% が60%下限を下回りました",
                    "context": {"nfav_ratio": round(nfav_ratio, 4), "nav_total": nav_total},
                })

        # LTV breaches on individual vehicles
        for sab in portfolio.get("items", []):
            ltv = sab.get("ltv_ratio")
            try:
                ltv_f = float(ltv) if ltv is not None else None
            except (TypeError, ValueError):
                ltv_f = None
            if ltv_f is not None and ltv_f > 0.60:
                flags.append({
                    "code": "ltv_breach",
                    "severity": "warning" if ltv_f <= 0.80 else "critical",
                    "message": f"LTV {ltv_f*100:.1f}% が60%を超過（SAB {sab.get('sab_number')}）",
                    "context": {"sab_id": sab.get("id"), "ltv": round(ltv_f, 4)},
                })

        # Overdue lease payments
        try:
            start, end = _month_bounds(report_month)
            resp = (
                self._client.table("lease_payments")
                .select("*")
                .eq("status", "overdue")
                .execute()
            )
            overdue = [p for p in (resp.data or []) if _in_month(p.get("scheduled_date"), start, end)]
            if overdue:
                flags.append({
                    "code": "overdue_payment",
                    "severity": "warning" if len(overdue) < 3 else "critical",
                    "message": f"{len(overdue)}件のリース料が延滞しています",
                    "context": {"count": len(overdue)},
                })
        except Exception:
            logger.exception("investor_report_overdue_check_failed", fund_id=str(fund_id))

        return flags

    # ------------------------------------------------------------------
    # PDF rendering
    # ------------------------------------------------------------------

    def _render_pdf(
        self,
        *,
        fund: dict[str, Any],
        report_month: date,
        nav_rows: list[dict[str, Any]],
        dividends: dict[str, list[dict[str, Any]]],
        portfolio: dict[str, Any],
        risk_flags: list[dict[str, Any]],
        nav_total: int,
        dividend_paid: int,
        dividend_scheduled: int,
    ) -> bytes:
        # Build a fresh fpdf2 document via the shared generator. We reach into
        # its private helpers — this module is intentionally co-located with
        # LightweightPDFGenerator so that contract stays stable.
        pdf, font = self._pdf._new_pdf()  # type: ignore[attr-defined]
        section = self._pdf._section_header  # type: ignore[attr-defined]
        kv = self._pdf._kv_row  # type: ignore[attr-defined]

        fund_name = fund.get("fund_name") or "(ファンド名未設定)"
        period_jp = f"{report_month.year}年{report_month.month:02d}月"

        # --- Page 1: Cover -----------------------------------------------------
        pdf.add_page()
        pdf.ln(60)
        pdf.set_font(font, "B", 26)
        pdf.set_text_color(26, 54, 93)
        pdf.cell(0, 14, "投資家月次報告書", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 14, "Investor Monthly Report", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(12)
        pdf.set_font(font, "", 14)
        pdf.set_text_color(74, 85, 104)
        pdf.cell(0, 8, fund_name, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"対象期間: {period_jp}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(20)
        pdf.set_font(font, "", 10)
        pdf.set_text_color(113, 128, 150)
        pdf.cell(0, 6, f"発行日: {date.today().strftime('%Y年%m月%d日')}", align="C",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "発行: 株式会社カーチスロジテック", align="C",
                 new_x="LMARGIN", new_y="NEXT")

        # --- Page 2: NAV summary + trend --------------------------------------
        pdf.add_page()
        section(pdf, font, "1. NAVサマリー / Net Fund Asset Value")

        kv(pdf, font, "期末NAV合計", f"Y{_yen(nav_total)}")
        kv(pdf, font, "車両台数", f"{portfolio.get('vehicle_count', 0)} 台")
        kv(pdf, font, "取得原価合計", f"Y{_yen(portfolio.get('total_acquisition', 0))}")
        kv(pdf, font, "時価評価合計", f"Y{_yen(portfolio.get('total_market_value', 0))}")
        pdf.ln(4)

        pdf.set_font(font, "B", 11)
        pdf.cell(0, 8, "直近12ヶ月 NAV推移", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, "B", 9)
        pdf.set_fill_color(26, 86, 219)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(40, 7, "月", border=1, fill=True, align="C")
        pdf.cell(45, 7, "NAV", border=1, fill=True, align="C")
        pdf.cell(45, 7, "簿価", border=1, fill=True, align="C")
        pdf.cell(45, 7, "時価", border=1, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(font, "", 9)
        monthly = _aggregate_nav_by_month(nav_rows)[:12]
        for m, agg in monthly:
            pdf.cell(40, 6, m, border=1)
            pdf.cell(45, 6, f"Y{_yen(agg['nav'])}", border=1, align="R")
            pdf.cell(45, 6, f"Y{_yen(agg['book_value'])}", border=1, align="R")
            pdf.cell(45, 6, f"Y{_yen(agg['market_value'])}", border=1, align="R",
                     new_x="LMARGIN", new_y="NEXT")
        if not monthly:
            pdf.cell(0, 6, "（NAV履歴がまだありません）", new_x="LMARGIN", new_y="NEXT")

        # --- Page 3: Dividend history -----------------------------------------
        pdf.add_page()
        section(pdf, font, "2. 配当履歴 / Dividend History")
        kv(pdf, font, "当月配当（実行済）", f"Y{_yen(dividend_paid)}")
        kv(pdf, font, "翌月配当（予定）", f"Y{_yen(dividend_scheduled)}")
        pdf.ln(4)

        pdf.set_font(font, "B", 9)
        pdf.set_fill_color(26, 86, 219)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(35, 7, "支払日", border=1, fill=True, align="C")
        pdf.cell(30, 7, "区分", border=1, fill=True, align="C")
        pdf.cell(45, 7, "金額", border=1, fill=True, align="C")
        pdf.cell(35, 7, "年換算利回り", border=1, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(font, "", 9)
        all_div = (dividends.get("paid") or []) + (dividends.get("scheduled") or [])
        all_div.sort(key=lambda r: str(r.get("distribution_date") or ""), reverse=True)
        for row in all_div[:24]:
            pdf.cell(35, 6, str(row.get("distribution_date", "-"))[:10], border=1)
            pdf.cell(30, 6, str(row.get("distribution_type", "-")), border=1, align="C")
            pdf.cell(45, 6, f"Y{_yen(row.get('distribution_amount', 0))}", border=1, align="R")
            ay = row.get("annualized_yield")
            ay_str = f"{float(ay) * 100:.2f}%" if ay not in (None, "") else "-"
            pdf.cell(35, 6, ay_str, border=1, align="R", new_x="LMARGIN", new_y="NEXT")
        if not all_div:
            pdf.cell(0, 6, "（配当履歴がまだありません）", new_x="LMARGIN", new_y="NEXT")

        # --- Page 4: Portfolio snapshot ---------------------------------------
        pdf.add_page()
        section(pdf, font, "3. ポートフォリオ構成 / Portfolio Snapshot")
        kv(pdf, font, "保有車両台数", f"{portfolio.get('vehicle_count', 0)} 台")
        kv(pdf, font, "取得原価合計", f"Y{_yen(portfolio.get('total_acquisition', 0))}")
        kv(pdf, font, "時価評価合計", f"Y{_yen(portfolio.get('total_market_value', 0))}")
        pdf.ln(4)

        pdf.set_font(font, "B", 9)
        pdf.set_fill_color(26, 86, 219)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(35, 7, "SAB番号", border=1, fill=True, align="C")
        pdf.cell(40, 7, "取得価額", border=1, fill=True, align="C")
        pdf.cell(40, 7, "時価評価", border=1, fill=True, align="C")
        pdf.cell(25, 7, "LTV", border=1, fill=True, align="C")
        pdf.cell(30, 7, "ステータス", border=1, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(font, "", 9)
        for sab in (portfolio.get("items") or [])[:25]:
            pdf.cell(35, 6, str(sab.get("sab_number", "-"))[:20], border=1)
            pdf.cell(40, 6, f"Y{_yen(sab.get('acquisition_price', 0))}", border=1, align="R")
            pdf.cell(40, 6, f"Y{_yen(sab.get('adjusted_valuation') or sab.get('b2b_wholesale_valuation', 0))}",
                     border=1, align="R")
            ltv = sab.get("ltv_ratio")
            ltv_str = f"{float(ltv) * 100:.1f}%" if ltv not in (None, "") else "-"
            pdf.cell(25, 6, ltv_str, border=1, align="R")
            pdf.cell(30, 6, str(sab.get("status", "-")), border=1, align="C",
                     new_x="LMARGIN", new_y="NEXT")
        if not portfolio.get("items"):
            pdf.cell(0, 6, "（保有車両がありません）", new_x="LMARGIN", new_y="NEXT")

        # --- Page 5: Risk flags + notes ---------------------------------------
        pdf.add_page()
        section(pdf, font, "4. リスクアラート / Risk Flags")
        if not risk_flags:
            pdf.set_font(font, "", 10)
            pdf.cell(0, 7, "当月、特記すべきリスクアラートはありません。",
                     new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font(font, "B", 9)
            pdf.set_fill_color(220, 38, 38)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(30, 7, "重大度", border=1, fill=True, align="C")
            pdf.cell(45, 7, "コード", border=1, fill=True, align="C")
            pdf.cell(0, 7, "内容", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.set_font(font, "", 9)
            for flag in risk_flags:
                pdf.cell(30, 6, str(flag.get("severity", "-")), border=1, align="C")
                pdf.cell(45, 6, str(flag.get("code", "-")), border=1)
                pdf.cell(0, 6, str(flag.get("message", "-")), border=1,
                         new_x="LMARGIN", new_y="NEXT")

        pdf.ln(8)
        section(pdf, font, "5. 留意事項 / Notes")
        pdf.set_font(font, "", 8)
        pdf.set_text_color(130, 130, 130)
        for note in [
            "・本資料は参考情報であり、将来の実績を保証するものではありません。",
            "・NAVおよびLTVはリース料回収・市場価格により毎月変動します。",
            "・詳細な数値根拠が必要な場合は運営事業者までお問い合わせください。",
            "・本資料の二次配布・複製を禁じます。",
        ]:
            pdf.multi_cell(0, 5, note)
            pdf.ln(1)

        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)
        return buf.read()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_date(val: Any) -> Optional[date]:
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


def _same_month(val: Any, anchor: date) -> bool:
    d = _parse_date(val)
    return bool(d and d.year == anchor.year and d.month == anchor.month)


def _in_month(val: Any, start: date, end: date) -> bool:
    d = _parse_date(val)
    return bool(d and start <= d <= end)


def _add_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


def _aggregate_nav_by_month(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, int]]]:
    """Sum NAV / book / market per month, newest first (up to 12 months)."""
    buckets: dict[str, dict[str, int]] = {}
    for r in rows:
        d = _parse_date(r.get("recording_date"))
        if not d:
            continue
        key = f"{d.year:04d}-{d.month:02d}"
        b = buckets.setdefault(key, {"nav": 0, "book_value": 0, "market_value": 0})
        b["nav"] += int(r.get("nav") or 0)
        b["book_value"] += int(r.get("book_value") or 0)
        b["market_value"] += int(r.get("market_value") or 0)
    # Newest first
    return sorted(buckets.items(), reverse=True)
