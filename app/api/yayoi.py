"""Yayoi Accounting Online API endpoints.

Provides endpoints for OAuth2 connection, invoice sync, and
financial data retrieval via the Yayoi Accounting integration.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import Client

from app.dependencies import get_current_user, get_supabase_client
from app.services.yayoi_service import YayoiService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/yayoi", tags=["yayoi"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class OAuthConnectResponse(BaseModel):
    authorize_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class SyncInvoicesRequest(BaseModel):
    fund_id: str
    month: str = Field(
        ...,
        description="Target month as YYYY-MM-DD (first day of month)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


class IntegrationSettings(BaseModel):
    yayoi_auto_sync_monthly: bool = False
    yayoi_sync_invoices: bool = True
    yayoi_sync_journals: bool = True


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def _get_yayoi_service(
    supabase: Client = Depends(get_supabase_client),
) -> YayoiService:
    return YayoiService(supabase_client=supabase)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/connect", response_model=OAuthConnectResponse)
async def initiate_oauth(
    user: dict = Depends(get_current_user),
    yayoi: YayoiService = Depends(_get_yayoi_service),
):
    """Initiate OAuth2 flow with Yayoi Accounting Online.

    Returns the authorization URL the frontend should redirect to.
    """
    if not yayoi.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Yayoi integration is not configured. Set YAYOI_CLIENT_ID and YAYOI_CLIENT_SECRET.",
        )

    state = secrets.token_urlsafe(32)
    authorize_url = yayoi.get_authorize_url(state=state)

    logger.info("yayoi_oauth_initiated", user_id=user.get("sub"))
    return OAuthConnectResponse(authorize_url=authorize_url, state=state)


@router.post("/callback")
async def oauth_callback(
    body: OAuthCallbackRequest,
    user: dict = Depends(get_current_user),
    yayoi: YayoiService = Depends(_get_yayoi_service),
):
    """Handle OAuth2 callback from Yayoi.

    Exchanges the authorization code for tokens and stores them.
    """
    try:
        result = await yayoi.authenticate(body.code)
        logger.info("yayoi_oauth_callback_success", user_id=user.get("sub"))
        return JSONResponse(
            content={
                "status": "connected",
                "expires_in": result.get("expires_in"),
                "dry_run": result.get("dry_run", False),
            }
        )
    except Exception as exc:
        logger.error("yayoi_oauth_callback_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth callback failed: {exc}",
        )


@router.post("/sync-invoices")
async def sync_invoices(
    body: SyncInvoicesRequest,
    user: dict = Depends(get_current_user),
    yayoi: YayoiService = Depends(_get_yayoi_service),
):
    """Sync approved invoices for a fund/month to Yayoi.

    Creates journal entries in Yayoi for each invoice not yet synced.
    """
    try:
        month = date.fromisoformat(body.month)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid month format. Use YYYY-MM-DD.",
        )

    try:
        result = await yayoi.batch_sync_invoices(body.fund_id, month)
        logger.info(
            "yayoi_sync_invoices_complete",
            user_id=user.get("sub"),
            fund_id=body.fund_id,
            month=body.month,
            **{k: v for k, v in result.items() if k != "errors"},
        )
        return JSONResponse(content=result)
    except Exception as exc:
        logger.error("yayoi_sync_invoices_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {exc}",
        )


@router.get("/financials/{company_code}")
async def get_financials(
    company_code: str,
    user: dict = Depends(get_current_user),
    yayoi: YayoiService = Depends(_get_yayoi_service),
):
    """Retrieve financial statements for a transport company.

    Returns P&L and balance sheet data for AI financial diagnosis.
    """
    try:
        data = await yayoi.get_company_financials(company_code)
        return JSONResponse(content=data)
    except Exception as exc:
        logger.error(
            "yayoi_financials_endpoint_failed",
            company=company_code,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve financials: {exc}",
        )


@router.get("/status")
async def connection_status(
    user: dict = Depends(get_current_user),
    yayoi: YayoiService = Depends(_get_yayoi_service),
):
    """Check Yayoi connection status.

    Returns a normalized ``state`` enum (``connected`` / ``disconnected`` /
    ``expired``) in addition to the raw service fields so the UI can render
    a single status badge without any extra logic.
    """
    raw = yayoi.get_connection_status()

    # Attempt to hydrate from the DB so the UI doesn't depend on a
    # long-lived in-memory token (YayoiService._load_tokens is a no-op if
    # Supabase is not wired in).
    try:
        await yayoi._load_tokens()  # type: ignore[attr-defined]
        raw = yayoi.get_connection_status()
    except Exception:
        pass

    expires = raw.get("token_expires")
    state = "disconnected"
    if raw.get("authenticated"):
        state = "connected"
        if expires:
            try:
                expiry = datetime.fromisoformat(expires)
                if expiry <= datetime.now(timezone.utc):
                    state = "expired"
            except ValueError:
                pass

    return JSONResponse(content={**raw, "state": state})


# ---------------------------------------------------------------------------
# Sync log / settings
# ---------------------------------------------------------------------------


@router.get("/sync-log")
async def list_sync_log(
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
):
    """Return the most recent Yayoi sync log rows (newest first)."""
    try:
        resp = (
            supabase.table("yayoi_sync_log")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return JSONResponse(content={"items": resp.data or []})
    except Exception as exc:
        logger.error("yayoi_sync_log_fetch_failed", error=str(exc))
        # Table may not exist in early envs — return empty set instead of 500.
        return JSONResponse(content={"items": [], "error": str(exc)})


def _default_settings_row(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "yayoi_auto_sync_monthly": False,
        "yayoi_sync_invoices": True,
        "yayoi_sync_journals": True,
    }


@router.get("/settings")
async def get_settings_endpoint(
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
):
    """Return the current user's integration settings.

    Creates a default row on first access so the UI always has something
    to bind to.
    """
    user_id = user.get("id") or user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user id missing",
        )

    try:
        resp = (
            supabase.table("user_integration_settings")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if rows:
            return JSONResponse(content=rows[0])

        # First access — insert default row.
        default_row = _default_settings_row(user_id)
        insert_resp = (
            supabase.table("user_integration_settings")
            .insert(default_row)
            .execute()
        )
        created = (insert_resp.data or [default_row])[0]
        return JSONResponse(content=created)
    except Exception as exc:
        logger.error("yayoi_settings_get_failed", error=str(exc))
        # Fall back to in-memory defaults so the UI is still usable.
        return JSONResponse(content=_default_settings_row(user_id))


@router.post("/settings")
async def upsert_settings_endpoint(
    body: IntegrationSettings,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client),
):
    """Upsert the current user's integration settings."""
    user_id = user.get("id") or user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user id missing",
        )

    payload = {
        "user_id": user_id,
        "yayoi_auto_sync_monthly": body.yayoi_auto_sync_monthly,
        "yayoi_sync_invoices": body.yayoi_sync_invoices,
        "yayoi_sync_journals": body.yayoi_sync_journals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = (
            supabase.table("user_integration_settings")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        row = (resp.data or [payload])[0]
        logger.info("yayoi_settings_saved", user_id=user_id)
        return JSONResponse(content=row)
    except Exception as exc:
        logger.error("yayoi_settings_upsert_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save settings: {exc}",
        )
