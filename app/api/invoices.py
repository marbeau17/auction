"""Invoice management API endpoints.

Provides endpoints to list, create, approve, send, and download invoices.
All endpoints require an authenticated user (JWT via cookie).  Endpoints
that may be called from HTMX return an HTML fragment when the ``HX-Request``
header is present; otherwise they return JSON.
"""

from __future__ import annotations

import io
import math
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from supabase import Client

from app.db.repositories.invoice_repo import InvoiceRepository
from app.core.http import content_disposition
from app.core.pdf_generator import LightweightPDFGenerator, HAS_FPDF
from app.dependencies import get_current_user, get_supabase_client, require_role
from app.middleware.rbac import get_user_role, require_permission
from app.models.common import (
    ErrorResponse,
    PaginatedResponse,
    PaginationMeta,
    SuccessResponse,
)
from app.models.invoice import (
    EmailLogResponse,
    InvoiceApprovalCreate,
    InvoiceApprovalResponse,
    InvoiceCreate,
    InvoiceResponse,
    InvoiceSendRequest,
    InvoiceStatusUpdate,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


class MonthlyGenerateRequest(BaseModel):
    """Body for the generate-monthly endpoint."""

    fund_id: UUID = Field(..., description="Target fund identifier")
    billing_month: date = Field(
        ...,
        description="Billing month (any day in the target month)",
        examples=["2026-04-01"],
    )


def _is_htmx(request: Request) -> bool:
    """Return ``True`` when the request originates from htmx."""
    return request.headers.get("HX-Request", "").lower() == "true"


def _get_repo(supabase: Client = Depends(get_supabase_client)) -> InvoiceRepository:
    """Provide an ``InvoiceRepository`` via dependency injection."""
    return InvoiceRepository(client=supabase)


# ---------------------------------------------------------------------------
# Fund-scoping helpers
# ---------------------------------------------------------------------------


def _accessible_fund_ids(
    supabase: Client, user: dict[str, Any]
) -> list[str] | None:
    """Return fund IDs the user may access, or ``None`` for unrestricted.

    Admins get full access (``None``). Other roles are scoped to funds they
    manage via ``funds.manager_user_id``. Users with no managed funds get an
    empty list, which callers should treat as "no access".
    """
    if get_user_role(user) == "admin":
        return None
    try:
        resp = (
            supabase.table("funds")
            .select("id")
            .eq("manager_user_id", user["id"])
            .execute()
        )
        return [str(row["id"]) for row in (resp.data or [])]
    except Exception:
        logger.exception(
            "accessible_fund_ids_failed", user_id=user.get("id")
        )
        return []


def _user_can_access_invoice(
    invoice: dict[str, Any],
    accessible_fund_ids: list[str] | None,
) -> bool:
    """Return True when the user may access this invoice.

    ``None`` accessible list means admin (allow all). An empty list means the
    user has no fund membership — deny. Otherwise the invoice's ``fund_id``
    must be in the list.
    """
    if accessible_fund_ids is None:
        return True
    fund_id = invoice.get("fund_id")
    if fund_id is None:
        return False
    return str(fund_id) in accessible_fund_ids


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _yen(value: int) -> str:
    """Format an integer as a Japanese-yen string."""
    return f"{value:,}"


_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "created": ("作成済", "text-gray-700 bg-gray-100"),
    "pending_review": ("確認待ち", "text-yellow-700 bg-yellow-100"),
    "approved": ("承認済", "text-green-700 bg-green-100"),
    "pdf_ready": ("PDF準備完了", "text-blue-700 bg-blue-100"),
    "sent": ("送信済", "text-indigo-700 bg-indigo-100"),
    "paid": ("入金済", "text-emerald-700 bg-emerald-100"),
    "overdue": ("期日超過", "text-red-700 bg-red-100"),
    "cancelled": ("取消", "text-gray-500 bg-gray-200"),
}


def _status_badge(status_val: str) -> str:
    """Return an HTML badge span for a given invoice status."""
    label, css = _STATUS_LABELS.get(status_val, (status_val, ""))
    return (
        f'<span class="px-2 py-0.5 rounded-full text-xs font-semibold {css}">'
        f"{label}</span>"
    )


# ---------------------------------------------------------------------------
# HTMX fragment renderers
# ---------------------------------------------------------------------------


def _render_invoice_table_fragment(
    invoices: list[dict[str, Any]],
    meta: PaginationMeta,
) -> str:
    """Return an HTML table fragment for the invoice list."""
    if not invoices:
        return '<p class="text-gray-500 py-4 text-center">請求書がありません。</p>'

    rows = ""
    for inv in invoices:
        created = inv.get("created_at", "")[:10]
        due = inv.get("due_date", "")
        rows += (
            f"<tr class='border-b hover:bg-gray-50'>"
            f"<td class='px-3 py-2'>"
            f"<a href='/invoices/{inv['id']}' "
            f"   hx-get='/api/v1/invoices/{inv['id']}' "
            f"   hx-target='#main-content' "
            f"   class='text-blue-600 hover:underline'>"
            f"{inv.get('invoice_number', '-')}</a></td>"
            f"<td class='px-3 py-2 text-right'>&yen;{_yen(inv.get('total_amount', 0))}</td>"
            f"<td class='px-3 py-2 text-center'>{_status_badge(inv.get('status', ''))}</td>"
            f"<td class='px-3 py-2 text-center'>{due}</td>"
            f"<td class='px-3 py-2 text-center'>{created}</td>"
            f"</tr>"
        )

    pagination = ""
    if meta.total_pages > 1:
        pages = "".join(
            f"<button hx-get='/api/v1/invoices?page={p}&per_page={meta.per_page}' "
            f"        hx-target='#invoice-list' hx-swap='innerHTML' "
            f"        class='px-3 py-1 border rounded "
            f"{'bg-blue-600 text-white' if p == meta.page else 'hover:bg-gray-100'}'>"
            f"{p}</button>"
            for p in range(1, meta.total_pages + 1)
        )
        pagination = f'<div class="flex gap-1 justify-center mt-4">{pages}</div>'

    return f"""
    <table class="w-full text-sm">
      <thead>
        <tr class="bg-gray-50 border-b">
          <th class="px-3 py-2 text-left">請求番号</th>
          <th class="px-3 py-2 text-right">合計金額</th>
          <th class="px-3 py-2 text-center">ステータス</th>
          <th class="px-3 py-2 text-center">支払期日</th>
          <th class="px-3 py-2 text-center">作成日</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    {pagination}
    """


def _render_status_update_fragment(invoice: dict[str, Any]) -> str:
    """Return an HTML fragment for an inline status badge update via HTMX."""
    return (
        f'<div id="invoice-status-{invoice["id"]}">'
        f'{_status_badge(invoice.get("status", ""))}'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# PDF generation (HTML-based)
# ---------------------------------------------------------------------------


def _generate_invoice_pdf_html(invoice: dict[str, Any]) -> str:
    """Generate an HTML document suitable for PDF rendering / download.

    The output is a self-contained HTML page styled for A4 printing.
    """
    line_items = invoice.get("line_items", [])
    items_rows = ""
    for idx, item in enumerate(line_items, start=1):
        items_rows += (
            f"<tr>"
            f"<td style='border:1px solid #ccc;padding:6px 10px;text-align:center;'>{idx}</td>"
            f"<td style='border:1px solid #ccc;padding:6px 10px;'>{item.get('description', '')}</td>"
            f"<td style='border:1px solid #ccc;padding:6px 10px;text-align:right;'>"
            f"{item.get('quantity', 1)}</td>"
            f"<td style='border:1px solid #ccc;padding:6px 10px;text-align:right;'>"
            f"&yen;{_yen(item.get('unit_price', 0))}</td>"
            f"<td style='border:1px solid #ccc;padding:6px 10px;text-align:right;'>"
            f"&yen;{_yen(item.get('amount', 0))}</td>"
            f"</tr>"
        )

    tax_pct = f"{float(invoice.get('tax_rate', 0.10)) * 100:.0f}"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>請求書 {invoice.get("invoice_number", "")}</title>
<style>
  @page {{ size: A4; margin: 20mm; }}
  body {{ font-family: 'Helvetica Neue', 'Hiragino Sans', sans-serif;
         font-size: 12px; color: #333; margin: 0; padding: 20px; }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start;
             margin-bottom: 30px; }}
  .header h1 {{ font-size: 24px; margin: 0; color: #1a56db; }}
  .meta-table {{ width: 100%; margin-bottom: 24px; }}
  .meta-table td {{ padding: 4px 8px; }}
  .meta-table .label {{ font-weight: bold; width: 140px; color: #555; }}
  .items-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  .items-table th {{ background: #1a56db; color: #fff; padding: 8px 10px;
                     text-align: center; font-size: 11px; }}
  .totals {{ width: 320px; margin-left: auto; margin-bottom: 30px; }}
  .totals td {{ padding: 4px 8px; }}
  .totals .total-row {{ font-weight: bold; font-size: 16px; border-top: 2px solid #333; }}
  .payment-info {{ background: #f9fafb; border: 1px solid #e5e7eb; padding: 16px;
                   border-radius: 4px; margin-bottom: 24px; }}
  .payment-info h3 {{ margin: 0 0 8px; font-size: 13px; color: #1a56db; }}
  .footer {{ text-align: center; font-size: 10px; color: #999;
             border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>請 求 書</h1>
    <p style="color:#666;margin:4px 0 0;">INVOICE</p>
  </div>
  <div style="text-align:right;">
    <p style="font-weight:bold;font-size:14px;">CVLPOS株式会社</p>
    <p style="font-size:11px;color:#666;margin:2px 0;">
      〒100-0001 東京都千代田区千代田1-1-1<br>
      TEL: 03-XXXX-XXXX<br>
      登録番号: T1234567890123
    </p>
  </div>
</div>

<table class="meta-table">
  <tr>
    <td class="label">請求番号:</td>
    <td>{invoice.get("invoice_number", "")}</td>
    <td class="label">請求日:</td>
    <td>{invoice.get("created_at", "")[:10]}</td>
  </tr>
  <tr>
    <td class="label">請求期間:</td>
    <td>{invoice.get("billing_period_start", "")} 〜 {invoice.get("billing_period_end", "")}</td>
    <td class="label">支払期日:</td>
    <td style="font-weight:bold;color:#dc2626;">{invoice.get("due_date", "")}</td>
  </tr>
</table>

<table class="items-table">
  <thead>
    <tr>
      <th style="width:40px;">No.</th>
      <th>摘要</th>
      <th style="width:60px;">数量</th>
      <th style="width:110px;">単価</th>
      <th style="width:110px;">金額</th>
    </tr>
  </thead>
  <tbody>
    {items_rows}
  </tbody>
</table>

<table class="totals">
  <tr>
    <td style="text-align:right;">小計:</td>
    <td style="text-align:right;">&yen;{_yen(invoice.get("subtotal", 0))}</td>
  </tr>
  <tr>
    <td style="text-align:right;">消費税（{tax_pct}%）:</td>
    <td style="text-align:right;">&yen;{_yen(invoice.get("tax_amount", 0))}</td>
  </tr>
  <tr class="total-row">
    <td style="text-align:right;padding-top:8px;">合計金額:</td>
    <td style="text-align:right;padding-top:8px;">&yen;{_yen(invoice.get("total_amount", 0))}</td>
  </tr>
</table>

<div class="payment-info">
  <h3>お振込先</h3>
  <p style="margin:0;font-size:12px;">
    三菱UFJ銀行 丸の内支店（001）<br>
    普通預金 1234567<br>
    口座名義: シーブイエルポス（カ
  </p>
</div>

{"<div style='background:#fff3cd;border:1px solid #ffc107;padding:10px;border-radius:4px;margin-bottom:16px;font-size:11px;'><strong>備考:</strong> " + invoice["notes"] + "</div>" if invoice.get("notes") else ""}

<div class="footer">
  この請求書はCVLPOSシステムにより自動生成されました。
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# 1. GET / - List invoices (paginated, filterable)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PaginatedResponse[dict[str, Any]],
    summary="List invoices",
    responses={
        200: {"description": "Paginated invoice list"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_invoices(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    fund_id: Optional[UUID] = Query(default=None, description="Filter by fund ID"),
    invoice_status: Optional[str] = Query(
        default=None, alias="status", description="Filter by invoice status"
    ),
    current_user: dict[str, Any] = Depends(require_permission("invoices", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return a paginated list of invoices with optional filters."""
    logger.info(
        "invoice_list",
        user_id=current_user["id"],
        fund_id=str(fund_id) if fund_id else None,
        status=invoice_status,
    )

    allowed_fund_ids = _accessible_fund_ids(supabase, current_user)

    # If the caller supplied an explicit ``fund_id`` filter, ensure they are
    # allowed to see it; otherwise the repo filter below would silently return
    # an empty page instead of communicating the denial.
    if (
        fund_id is not None
        and allowed_fund_ids is not None
        and str(fund_id) not in allowed_fund_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="指定されたファンドへのアクセス権限がありません",
        )

    items, total_count = await repo.list_invoices(
        fund_id=fund_id,
        status=invoice_status,
        page=page,
        per_page=per_page,
        allowed_fund_ids=allowed_fund_ids,
    )

    total_pages = max(1, math.ceil(total_count / per_page))
    meta = PaginationMeta(
        total_count=total_count,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )

    if _is_htmx(request):
        html = _render_invoice_table_fragment(items, meta)
        return HTMLResponse(content=html)

    return JSONResponse(
        content=PaginatedResponse[dict[str, Any]](
            data=items,
            meta=meta,
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 2. GET /overdue - List overdue invoices
# ---------------------------------------------------------------------------


@router.get(
    "/overdue",
    response_model=SuccessResponse,
    summary="List overdue invoices",
    responses={
        200: {"description": "List of overdue invoices"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_overdue_invoices(
    request: Request,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return all invoices that are past their due date and not paid."""
    logger.info("invoice_overdue_list", user_id=current_user["id"])

    allowed_fund_ids = _accessible_fund_ids(supabase, current_user)
    overdue = await repo.get_overdue_invoices(allowed_fund_ids=allowed_fund_ids)

    if _is_htmx(request):
        if not overdue:
            return HTMLResponse(
                content='<p class="text-gray-500 py-4 text-center">期日超過の請求書はありません。</p>'
            )

        rows = ""
        for inv in overdue:
            rows += (
                f"<tr class='border-b hover:bg-red-50'>"
                f"<td class='px-3 py-2'>"
                f"<a href='/invoices/{inv['id']}' class='text-blue-600 hover:underline'>"
                f"{inv.get('invoice_number', '-')}</a></td>"
                f"<td class='px-3 py-2 text-right'>&yen;{_yen(inv.get('total_amount', 0))}</td>"
                f"<td class='px-3 py-2 text-center text-red-600 font-semibold'>"
                f"{inv.get('due_date', '')}</td>"
                f"<td class='px-3 py-2 text-center'>{_status_badge(inv.get('status', ''))}</td>"
                f"</tr>"
            )

        html = f"""
        <table class="w-full text-sm">
          <thead>
            <tr class="bg-red-50 border-b">
              <th class="px-3 py-2 text-left">請求番号</th>
              <th class="px-3 py-2 text-right">合計金額</th>
              <th class="px-3 py-2 text-center">支払期日</th>
              <th class="px-3 py-2 text-center">ステータス</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """
        return HTMLResponse(content=html)

    return JSONResponse(
        content=SuccessResponse(
            data=overdue,
            meta={"count": len(overdue)},
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 3. GET /{invoice_id} - Get invoice detail with line items
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_id}",
    response_model=SuccessResponse,
    summary="Get invoice detail",
    responses={
        200: {"description": "Invoice detail with line items"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def get_invoice(
    request: Request,
    invoice_id: UUID,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return the full detail of a single invoice including line items."""
    logger.info(
        "invoice_get",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
    )

    invoice = await repo.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    allowed_fund_ids = _accessible_fund_ids(supabase, current_user)
    if not _user_can_access_invoice(invoice, allowed_fund_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この請求書へのアクセス権限がありません",
        )

    if _is_htmx(request):
        line_items = invoice.get("line_items", [])
        items_html = ""
        for item in line_items:
            items_html += (
                f"<tr class='border-b'>"
                f"<td class='px-3 py-2'>{item.get('description', '')}</td>"
                f"<td class='px-3 py-2 text-right'>{item.get('quantity', 1)}</td>"
                f"<td class='px-3 py-2 text-right'>&yen;{_yen(item.get('unit_price', 0))}</td>"
                f"<td class='px-3 py-2 text-right'>&yen;{_yen(item.get('amount', 0))}</td>"
                f"</tr>"
            )

        html = f"""
        <div class="space-y-4">
          <div class="flex justify-between items-center">
            <h2 class="text-xl font-bold">{invoice.get("invoice_number", "")}</h2>
            <div id="invoice-status-{invoice['id']}">{_status_badge(invoice.get("status", ""))}</div>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="p-3 border rounded">
              <p class="text-xs text-gray-500">請求期間</p>
              <p class="font-semibold">{invoice.get("billing_period_start", "")} 〜 {invoice.get("billing_period_end", "")}</p>
            </div>
            <div class="p-3 border rounded">
              <p class="text-xs text-gray-500">支払期日</p>
              <p class="font-semibold">{invoice.get("due_date", "")}</p>
            </div>
            <div class="p-3 border rounded">
              <p class="text-xs text-gray-500">小計</p>
              <p class="font-semibold">&yen;{_yen(invoice.get("subtotal", 0))}</p>
            </div>
            <div class="p-3 border rounded">
              <p class="text-xs text-gray-500">合計金額（税込）</p>
              <p class="text-lg font-bold">&yen;{_yen(invoice.get("total_amount", 0))}</p>
            </div>
          </div>
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 border-b">
                <th class="px-3 py-2 text-left">摘要</th>
                <th class="px-3 py-2 text-right">数量</th>
                <th class="px-3 py-2 text-right">単価</th>
                <th class="px-3 py-2 text-right">金額</th>
              </tr>
            </thead>
            <tbody>{items_html}</tbody>
          </table>
        </div>
        """
        return HTMLResponse(content=html)

    return JSONResponse(
        content=SuccessResponse(data=invoice).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 4. POST / - Create invoice manually
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invoice",
    responses={
        201: {"description": "Invoice created successfully"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def create_invoice(
    request: Request,
    body: InvoiceCreate,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "write")),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Create a new invoice with line items."""
    logger.info(
        "invoice_create",
        user_id=current_user["id"],
        invoice_number=body.invoice_number,
    )

    now = datetime.now(timezone.utc).isoformat()
    invoice_data: dict[str, Any] = {
        "fund_id": str(body.fund_id),
        "lease_contract_id": str(body.lease_contract_id),
        "invoice_number": body.invoice_number,
        "billing_period_start": body.billing_period_start.isoformat(),
        "billing_period_end": body.billing_period_end.isoformat(),
        "subtotal": body.subtotal,
        "tax_rate": body.tax_rate,
        "tax_amount": body.tax_amount,
        "total_amount": body.total_amount,
        "due_date": body.due_date.isoformat(),
        "notes": body.notes,
        "status": "created",
        "created_at": now,
        "updated_at": now,
    }

    line_items = [item.model_dump() for item in body.line_items]

    try:
        invoice = await repo.create_invoice(invoice_data, line_items)
    except Exception:
        logger.exception("invoice_create_failed", user_id=current_user["id"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="請求書の作成中にエラーが発生しました",
        )

    if _is_htmx(request):
        return HTMLResponse(
            content=(
                '<div class="p-4 bg-green-50 border border-green-200 rounded text-green-800">'
                f'請求書 {invoice.get("invoice_number", "")} を作成しました。'
                "</div>"
            ),
            status_code=201,
        )

    return JSONResponse(
        content=SuccessResponse(
            data=invoice,
            meta={"invoice_id": str(invoice["id"])},
        ).model_dump(mode="json"),
        status_code=201,
    )


# ---------------------------------------------------------------------------
# 5. POST /generate-monthly - Auto-generate monthly invoices
# ---------------------------------------------------------------------------


@router.post(
    "/generate-monthly",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate monthly invoices for a fund",
    responses={
        201: {"description": "Monthly invoices generated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def generate_monthly_invoices(
    request: Request,
    body: MonthlyGenerateRequest,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "write")),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Auto-generate invoices for all active lease contracts in a fund."""
    logger.info(
        "invoice_generate_monthly",
        user_id=current_user["id"],
        fund_id=str(body.fund_id),
        billing_month=body.billing_month.isoformat(),
    )

    try:
        invoices = await repo.generate_monthly_invoices(
            fund_id=body.fund_id,
            billing_month=body.billing_month,
        )
    except Exception:
        logger.exception(
            "invoice_generate_monthly_failed",
            user_id=current_user["id"],
            fund_id=str(body.fund_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="月次請求書の自動生成中にエラーが発生しました",
        )

    if _is_htmx(request):
        return HTMLResponse(
            content=(
                '<div class="p-4 bg-green-50 border border-green-200 rounded text-green-800">'
                f"{len(invoices)} 件の請求書を生成しました。"
                "</div>"
            ),
            status_code=201,
        )

    return JSONResponse(
        content=SuccessResponse(
            data=invoices,
            meta={"generated_count": len(invoices)},
        ).model_dump(mode="json"),
        status_code=201,
    )


# ---------------------------------------------------------------------------
# 6. PUT /{invoice_id}/status - Update invoice status
# ---------------------------------------------------------------------------


@router.put(
    "/{invoice_id}/status",
    response_model=SuccessResponse,
    summary="Update invoice status",
    responses={
        200: {"description": "Status updated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def update_invoice_status(
    request: Request,
    invoice_id: UUID,
    body: InvoiceStatusUpdate,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "write")),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Update the status of an invoice."""
    logger.info(
        "invoice_status_update",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
        new_status=body.status,
    )

    # Verify invoice exists
    existing = await repo.get_invoice(invoice_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    try:
        updated = await repo.update_invoice_status(invoice_id, body.status)
    except Exception:
        logger.exception(
            "invoice_status_update_failed",
            invoice_id=str(invoice_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ステータス更新中にエラーが発生しました",
        )

    if _is_htmx(request):
        return HTMLResponse(content=_render_status_update_fragment(updated))

    return JSONResponse(
        content=SuccessResponse(data=updated).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 7. POST /{invoice_id}/approve - Approve / reject an invoice
# ---------------------------------------------------------------------------


@router.post(
    "/{invoice_id}/approve",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Approve or reject an invoice",
    responses={
        201: {"description": "Approval recorded"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def approve_invoice(
    request: Request,
    invoice_id: UUID,
    body: InvoiceApprovalCreate,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "write")),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Record an approval, rejection, or change-request decision."""
    logger.info(
        "invoice_approve",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
        action=body.action,
    )

    # Verify invoice exists
    existing = await repo.get_invoice(invoice_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    approval_data: dict[str, Any] = {
        "invoice_id": str(invoice_id),
        "approver_user_id": current_user["id"],
        "action": body.action,
        "comment": body.comment,
    }

    try:
        approval = await repo.create_approval(approval_data)
    except Exception:
        logger.exception(
            "invoice_approve_failed",
            invoice_id=str(invoice_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="承認処理中にエラーが発生しました",
        )

    action_labels = {
        "approve": "承認",
        "reject": "却下",
        "request_change": "修正依頼",
    }

    if _is_htmx(request):
        label = action_labels.get(body.action, body.action)
        # Re-fetch to get the updated status
        updated_invoice = await repo.get_invoice(invoice_id)
        status_html = _render_status_update_fragment(updated_invoice or existing)
        return HTMLResponse(
            content=(
                f'<div class="p-4 bg-green-50 border border-green-200 rounded text-green-800 mb-2">'
                f"{label}しました。"
                f"</div>"
                f"{status_html}"
            ),
            status_code=201,
        )

    return JSONResponse(
        content=SuccessResponse(
            data=approval,
            meta={"action": body.action},
        ).model_dump(mode="json"),
        status_code=201,
    )


# ---------------------------------------------------------------------------
# 8. POST /{invoice_id}/send - Send invoice via email
# ---------------------------------------------------------------------------


@router.post(
    "/{invoice_id}/send",
    response_model=SuccessResponse,
    summary="Send invoice via email",
    responses={
        200: {"description": "Email sent (or queued)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def send_invoice(
    request: Request,
    invoice_id: UUID,
    body: InvoiceSendRequest,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "write")),
    repo: InvoiceRepository = Depends(_get_repo),
    supabase: Client = Depends(get_supabase_client),
) -> HTMLResponse | JSONResponse:
    """Send an invoice to the specified email address.

    Delegates the actual delivery to :class:`EmailService`, which honours
    the ``EMAIL_DRY_RUN`` setting (logs instead of hitting SMTP) and is
    responsible for writing the corresponding ``email_logs`` row with a
    ``sent`` / ``failed`` status.  On success the invoice status is
    promoted to ``sent``; on failure it is moved to ``failed``.
    """
    from app.services.email_service import EmailService

    logger.info(
        "invoice_send",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
        recipient=body.recipient_email,
    )

    # Load the full invoice (with line items) — needed for both the email
    # body and the PDF attachment.
    invoice = await repo.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    # --- Build PDF bytes (reuses fpdf2 path from GET /{invoice_id}/pdf) ---
    pdf_bytes: Optional[bytes] = None
    if body.include_pdf and HAS_FPDF:
        try:
            pdf_bytes = LightweightPDFGenerator().generate_invoice_pdf(invoice)
        except Exception:
            logger.exception(
                "invoice_pdf_build_failed_for_email",
                invoice_id=str(invoice_id),
            )
            pdf_bytes = None

    # --- Delegate to EmailService (handles dry-run + email_logs row) ---
    service = EmailService(supabase_client=supabase)
    try:
        result = await service.send_invoice_email(
            recipient_email=body.recipient_email,
            invoice_data=invoice,
            pdf_bytes=pdf_bytes,
            subject=body.subject,
        )
    except Exception:
        logger.exception(
            "invoice_email_send_failed",
            invoice_id=str(invoice_id),
        )
        try:
            await repo.update_invoice_status(invoice_id, "failed")
        except Exception:
            logger.exception(
                "invoice_status_failed_update_failed",
                invoice_id=str(invoice_id),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="メール送信処理中にエラーが発生しました",
        )

    send_status = result.get("status", "failed")

    # Mirror delivery outcome onto the invoice record.
    try:
        new_invoice_status = "sent" if send_status == "sent" else "failed"
        await repo.update_invoice_status(invoice_id, new_invoice_status)
    except Exception:
        logger.exception(
            "invoice_status_sync_failed",
            invoice_id=str(invoice_id),
            send_status=send_status,
        )

    if send_status != "sent":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"メール送信に失敗しました: {result.get('error_message') or '不明なエラー'}"
            ),
        )

    if _is_htmx(request):
        return HTMLResponse(
            content=(
                '<div class="p-4 bg-green-50 border border-green-200 rounded text-green-800">'
                f"{body.recipient_email} へ請求書を送信しました。"
                "</div>"
            ),
        )

    return JSONResponse(
        content=SuccessResponse(
            data=result,
            meta={"recipient": body.recipient_email, "status": send_status},
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 9. GET /{invoice_id}/pdf - Generate / download invoice PDF
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_id}/pdf",
    summary="Generate and download invoice PDF",
    responses={
        200: {"description": "Invoice PDF document (or HTML fallback)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def get_invoice_pdf(
    invoice_id: UUID,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvoiceRepository = Depends(_get_repo),
) -> StreamingResponse:
    """Generate and download an invoice PDF.

    Uses fpdf2 (lightweight, no native deps) when available to produce a
    real PDF.  Falls back to the original self-contained HTML page when
    fpdf2 is not installed.
    """
    logger.info(
        "invoice_pdf_generate",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
    )

    invoice = await repo.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    allowed_fund_ids = _accessible_fund_ids(supabase, current_user)
    if not _user_can_access_invoice(invoice, allowed_fund_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この請求書へのアクセス権限がありません",
        )

    invoice_number = invoice.get("invoice_number", str(invoice_id)[:8])

    # --- Attempt: fpdf2 lightweight PDF ---
    if HAS_FPDF:
        try:
            gen = LightweightPDFGenerator()
            pdf_bytes = gen.generate_invoice_pdf(invoice)
            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": content_disposition(
                        f"{invoice_number}.pdf"
                    ),
                },
            )
        except Exception:
            logger.exception("fpdf2_invoice_failed", invoice_id=str(invoice_id))

    # --- Fallback: HTML ---
    html_content = _generate_invoice_pdf_html(invoice)
    buffer = io.BytesIO(html_content.encode("utf-8"))

    return StreamingResponse(
        buffer,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(
                f"{invoice_number}.html"
            ),
        },
    )


# ---------------------------------------------------------------------------
# 10. GET /{invoice_id}/approvals - Get approval history
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_id}/approvals",
    response_model=SuccessResponse,
    summary="Get approval history for an invoice",
    responses={
        200: {"description": "Approval history"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def get_invoice_approvals(
    request: Request,
    invoice_id: UUID,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return the approval history for a single invoice."""
    logger.info(
        "invoice_approvals_get",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
    )

    # Verify invoice exists
    existing = await repo.get_invoice(invoice_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    allowed_fund_ids = _accessible_fund_ids(supabase, current_user)
    if not _user_can_access_invoice(existing, allowed_fund_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この請求書へのアクセス権限がありません",
        )

    approvals = await repo.get_approvals(invoice_id)

    if _is_htmx(request):
        if not approvals:
            return HTMLResponse(
                content='<p class="text-gray-500 py-2 text-center text-sm">承認履歴はありません。</p>'
            )

        action_labels = {
            "approve": ("承認", "text-green-700"),
            "reject": ("却下", "text-red-700"),
            "request_change": ("修正依頼", "text-yellow-700"),
        }

        rows = ""
        for appr in approvals:
            label, css = action_labels.get(
                appr.get("action", ""), (appr.get("action", ""), "")
            )
            created = appr.get("created_at", "")[:19].replace("T", " ")
            rows += (
                f"<tr class='border-b'>"
                f"<td class='px-3 py-2 {css} font-semibold'>{label}</td>"
                f"<td class='px-3 py-2'>{appr.get('comment', '') or '-'}</td>"
                f"<td class='px-3 py-2 text-center text-xs text-gray-500'>{created}</td>"
                f"</tr>"
            )

        html = f"""
        <table class="w-full text-sm">
          <thead>
            <tr class="bg-gray-50 border-b">
              <th class="px-3 py-2 text-left">アクション</th>
              <th class="px-3 py-2 text-left">コメント</th>
              <th class="px-3 py-2 text-center">日時</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """
        return HTMLResponse(content=html)

    return JSONResponse(
        content=SuccessResponse(
            data=approvals,
            meta={"count": len(approvals)},
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# 11. GET /{invoice_id}/email-logs - Get email send history
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_id}/email-logs",
    response_model=SuccessResponse,
    summary="Get email send history for an invoice",
    responses={
        200: {"description": "Email log history"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Invoice not found"},
    },
)
async def get_invoice_email_logs(
    request: Request,
    invoice_id: UUID,
    current_user: dict[str, Any] = Depends(require_permission("invoices", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvoiceRepository = Depends(_get_repo),
) -> HTMLResponse | JSONResponse:
    """Return the email send history for a single invoice."""
    logger.info(
        "invoice_email_logs_get",
        user_id=current_user["id"],
        invoice_id=str(invoice_id),
    )

    # Verify invoice exists
    existing = await repo.get_invoice(invoice_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="請求書が見つかりません",
        )

    allowed_fund_ids = _accessible_fund_ids(supabase, current_user)
    if not _user_can_access_invoice(existing, allowed_fund_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この請求書へのアクセス権限がありません",
        )

    logs = await repo.get_email_logs(invoice_id)

    if _is_htmx(request):
        if not logs:
            return HTMLResponse(
                content='<p class="text-gray-500 py-2 text-center text-sm">送信履歴はありません。</p>'
            )

        status_labels = {
            "pending": ("送信中", "text-yellow-600"),
            "sent": ("送信済", "text-green-600"),
            "failed": ("失敗", "text-red-600"),
        }

        rows = ""
        for log in logs:
            s_label, s_css = status_labels.get(
                log.get("status", ""), (log.get("status", ""), "")
            )
            created = log.get("created_at", "")[:19].replace("T", " ")
            rows += (
                f"<tr class='border-b'>"
                f"<td class='px-3 py-2'>{log.get('recipient_email', '')}</td>"
                f"<td class='px-3 py-2'>{log.get('subject', '')}</td>"
                f"<td class='px-3 py-2 text-center {s_css} font-semibold'>{s_label}</td>"
                f"<td class='px-3 py-2 text-center text-xs text-gray-500'>{created}</td>"
                f"</tr>"
            )

        html = f"""
        <table class="w-full text-sm">
          <thead>
            <tr class="bg-gray-50 border-b">
              <th class="px-3 py-2 text-left">送信先</th>
              <th class="px-3 py-2 text-left">件名</th>
              <th class="px-3 py-2 text-center">ステータス</th>
              <th class="px-3 py-2 text-center">日時</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """
        return HTMLResponse(content=html)

    return JSONResponse(
        content=SuccessResponse(
            data=logs,
            meta={"count": len(logs)},
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# Test email endpoint (admin only)
# ---------------------------------------------------------------------------


class TestEmailRequest(BaseModel):
    """Body for the test-email endpoint."""

    recipient_email: str = Field(..., description="Email address to send the test to")


@router.post(
    "/test-email",
    summary="Send a test email to verify SMTP configuration",
    responses={200: {"model": SuccessResponse}, 403: {"model": ErrorResponse}},
)
async def send_test_email(
    body: TestEmailRequest,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    supabase: Client = Depends(get_supabase_client),
):
    """Send a test invoice email to verify that the SMTP settings are correct.

    Only accessible to admin users.  Uses sample invoice data so no real
    invoice record is required.
    """
    from app.services.email_service import EmailService

    sample_invoice = {
        "id": None,
        "invoice_number": "TEST-0000",
        "billing_period_start": "2026-04-01",
        "billing_period_end": "2026-04-30",
        "total_amount": 123456,
        "due_date": "2026-05-31",
    }

    service = EmailService(supabase_client=supabase)
    result = await service.send_invoice_email(
        recipient_email=body.recipient_email,
        invoice_data=sample_invoice,
        subject="【テスト】SMTP設定確認メール",
    )

    if result["status"] == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SMTP送信に失敗しました: {result['error_message']}",
        )

    return JSONResponse(
        content=SuccessResponse(
            data=result,
            meta={"message": "テストメールを送信しました。"},
        ).model_dump(mode="json"),
    )
