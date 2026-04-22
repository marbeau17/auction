"""Investor monthly report API (INV-004).

Endpoints
---------
* ``POST /api/v1/investor-reports/generate`` — generate + persist a report.
  Requires the ``fund_info:read`` permission (admin/operator/AM).
* ``GET  /api/v1/investor-reports``           — list reports (investor scope
  enforced server-side via fund-investor email match).
* ``GET  /api/v1/investor-reports/{id}/download`` — mint a 15-min HMAC-signed
  token and return ``{download_url, expires_at}``.
* ``GET  /api/v1/investor-reports/download/{token}`` — redeem the token and
  stream the PDF bytes; records ``downloaded_at`` on the access log.

Signed-URL scheme
-----------------
The token is a compact HMAC-SHA256 MAC of ``{report_id, uid, exp}`` serialised
as URL-safe base64 JSON — no Supabase Storage signed URL is needed (tests and
local dev run without a live bucket). The signing key is ``APP_SECRET_KEY``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from supabase import Client

from app.config import Settings, get_settings
from app.core.http import content_disposition
from app.core.investor_report_generator import InvestorReportGenerator
from app.db.repositories.investor_report_repo import InvestorReportRepository
from app.dependencies import get_current_user, get_supabase_client
from app.middleware.rbac import get_user_role, require_permission
from app.models.common import ErrorResponse, SuccessResponse
from app.models.investor_report import (
    InvestorReportGenerateRequest,
    SignedDownloadResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/investor-reports", tags=["investor-reports"])


SIGNED_URL_TTL_SECONDS = 15 * 60  # 15 minutes per spec


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _mint_token(report_id: str, user_id: str, settings: Settings) -> tuple[str, datetime]:
    """Return (token, expires_at).

    Token layout: ``<payload_b64>.<sig_b64>`` where payload encodes
    ``{"rid": report_id, "uid": user_id, "exp": unix_ts}``.
    """
    exp_dt = datetime.now(timezone.utc) + timedelta(seconds=SIGNED_URL_TTL_SECONDS)
    payload = {
        "rid": report_id,
        "uid": user_id,
        "exp": int(exp_dt.timestamp()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(sig)
    token = f"{payload_b64}.{sig_b64}"
    return token, exp_dt


def _verify_token(token: str, settings: Settings) -> dict[str, Any]:
    """Validate signature + expiry; return the decoded payload dict.

    Raises :class:`HTTPException` with 401/403 status on any failure.
    """
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ダウンロードトークンの形式が不正です",
        ) from exc

    expected_sig = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ダウンロードトークンの形式が不正です",
        ) from exc

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの署名が無効です",
        )

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ダウンロードトークンの内容を解析できません",
        ) from exc

    exp = int(payload.get("exp", 0))
    if exp < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ダウンロードURLの有効期限が切れています",
        )
    return payload


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_repo(supabase: Client = Depends(get_supabase_client)) -> InvestorReportRepository:
    return InvestorReportRepository(client=supabase)


async def _investor_allowed_for_fund(
    client: Any, user: dict[str, Any], fund_id: str
) -> bool:
    """True if the caller has read access to this fund's reports."""
    if get_user_role(user) == "admin":
        return True
    # Operators / asset managers also have fund_info:read via RBAC_MATRIX;
    # scope-check only applies to role == 'investor'.
    if get_user_role(user) != "investor":
        # fund_info:read covers these roles globally at the API layer — the
        # repository call itself is still RLS-gated at the DB.
        from app.middleware.rbac import check_permission
        return check_permission("fund_info", "read", user)

    email = (user.get("email") or "").lower()
    if not email:
        return False
    try:
        resp = (
            client.table("fund_investors")
            .select("id")
            .eq("fund_id", fund_id)
            .eq("is_active", True)
            .execute()
        )
        rows = resp.data or []
        # We can't easily filter by lower(email) over the wire, so check here.
        for row in rows:
            if (row.get("investor_contact_email") or "").lower() == email:
                return True
    except Exception:
        logger.exception("investor_scope_check_failed", fund_id=fund_id)
    return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a monthly investor report",
    responses={
        201: {"description": "Report generated"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def generate_report(
    body: InvestorReportGenerateRequest,
    current_user: dict[str, Any] = Depends(require_permission("fund_info", "read")),
    supabase: Client = Depends(get_supabase_client),
    repo: InvestorReportRepository = Depends(_get_repo),
) -> JSONResponse:
    """Build the PDF, upload to storage (best-effort), and persist the row."""
    logger.info(
        "investor_report_generate",
        user_id=current_user.get("id"),
        fund_id=str(body.fund_id),
        report_month=body.report_month.isoformat(),
    )

    generator = InvestorReportGenerator(client=supabase)

    try:
        pdf_bytes, metrics = generator.generate(body.fund_id, body.report_month)
    except Exception:
        logger.exception(
            "investor_report_generate_failed",
            fund_id=str(body.fund_id),
            report_month=body.report_month.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="投資家レポートの生成中にエラーが発生しました",
        )

    storage_path = f"{body.fund_id}/{body.report_month.strftime('%Y-%m')}.pdf"

    # Best-effort upload to Supabase Storage; the row is still persisted even
    # if the bucket is unavailable (e.g. local dev without storage configured).
    try:
        bucket = supabase.storage.from_("investor-reports")
        bucket.upload(
            storage_path,
            pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
    except Exception:
        logger.warning(
            "investor_report_storage_upload_skipped",
            storage_path=storage_path,
            exc_info=True,
        )

    payload: dict[str, Any] = {
        "fund_id": str(body.fund_id),
        "report_month": body.report_month.isoformat(),
        "storage_path": storage_path,
        "nav_total": int(metrics["nav_total"]),
        "dividend_paid": int(metrics["dividend_paid"]),
        "dividend_scheduled": int(metrics["dividend_scheduled"]),
        "risk_flags": metrics["risk_flags"],
        "generated_by": current_user.get("id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    row = await repo.upsert_for_month(body.fund_id, body.report_month, payload)

    return JSONResponse(
        content=SuccessResponse(
            data=row,
            meta={"bytes": len(pdf_bytes), "risk_flag_count": len(metrics["risk_flags"])},
        ).model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )


@router.get(
    "",
    response_model=SuccessResponse,
    summary="List investor reports",
    responses={200: {"description": "List of reports"}, 401: {"model": ErrorResponse}},
)
async def list_reports(
    fund_id: UUID = Query(..., description="Fund identifier"),
    current_user: dict[str, Any] = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
    repo: InvestorReportRepository = Depends(_get_repo),
) -> JSONResponse:
    """Return up to 24 most-recent reports for the fund."""
    if not await _investor_allowed_for_fund(supabase, current_user, str(fund_id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このファンドのレポートへのアクセス権限がありません",
        )

    reports = await repo.list_by_fund(fund_id)
    return JSONResponse(
        content=SuccessResponse(
            data=reports,
            meta={"count": len(reports)},
        ).model_dump(mode="json"),
    )


@router.get(
    "/{report_id}/download",
    response_model=SignedDownloadResponse,
    summary="Mint a 15-minute signed download URL",
    responses={
        200: {"description": "Signed URL minted"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def create_download_url(
    report_id: UUID,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
    repo: InvestorReportRepository = Depends(_get_repo),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Issue an HMAC-signed token and log it in ``investor_report_access_logs``."""
    report = await repo.get(report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="レポートが見つかりません",
        )

    if not await _investor_allowed_for_fund(supabase, current_user, report["fund_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このレポートへのアクセス権限がありません",
        )

    token, exp_dt = _mint_token(str(report_id), current_user.get("id", ""), settings)
    token_hash = _hash_token(token)

    try:
        await repo.record_access(
            report_id=report_id,
            accessed_by=current_user.get("id"),
            signed_url_hash=token_hash,
            expires_at=exp_dt,
            ip_address=request.client.host if request.client else None,
        )
    except Exception:
        logger.exception("investor_report_access_log_insert_failed")

    # Build an absolute URL when possible, fall back to a relative path.
    base = str(request.base_url).rstrip("/")
    download_url = f"{base}/api/v1/investor-reports/download/{token}"

    return JSONResponse(
        content=SignedDownloadResponse(
            download_url=download_url,
            expires_at=exp_dt,
        ).model_dump(mode="json"),
    )


@router.get(
    "/download/{token}",
    summary="Redeem a signed token and stream the PDF",
    responses={
        200: {"description": "PDF stream"},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def download_report(
    token: str,
    request: Request,
    supabase: Client = Depends(get_supabase_client),
    repo: InvestorReportRepository = Depends(_get_repo),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Validate the token, regenerate the PDF, and return it as a download."""
    payload = _verify_token(token, settings)
    report_id = payload.get("rid")
    if not report_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="トークンの内容が不正です",
        )

    report = await repo.get(report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="レポートが見つかりません",
        )

    token_hash = _hash_token(token)
    try:
        await repo.mark_downloaded(
            signed_url_hash=token_hash,
            ip_address=request.client.host if request.client else None,
        )
    except Exception:
        logger.exception("investor_report_access_log_flip_failed")

    # Re-render from live data. (Alternative: fetch the stored PDF from Supabase
    # Storage via ``report["storage_path"]``; we use live-render so the flow works
    # without a real bucket.)
    try:
        generator = InvestorReportGenerator(client=supabase)
        month = date.fromisoformat(str(report["report_month"])[:10])
        pdf_bytes, _ = generator.generate(report["fund_id"], month)
    except Exception:
        logger.exception(
            "investor_report_regeneration_failed", report_id=str(report_id)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF生成に失敗しました",
        )

    filename = f"investor-report-{str(report['fund_id'])[:8]}-{report['report_month']}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(filename)},
    )
