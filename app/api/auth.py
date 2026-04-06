"""Authentication API router.

Handles login, logout, token refresh, and current-user retrieval.
Supports both standard browser requests and HTMX partial requests.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db.supabase_client import get_supabase_client
from app.dependencies import get_current_user, require_role  # noqa: F401 – re-exported

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_htmx(request: Request) -> bool:
    """Return ``True`` when the incoming request was issued by htmx."""
    return request.headers.get("HX-Request", "").lower() == "true"


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    """Write HttpOnly auth cookies onto *response*."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    """Remove auth cookies from *response*."""
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Authenticate a user via Supabase email/password sign-in.

    On success the JWT pair is stored in HttpOnly cookies and the client is
    redirected to ``/dashboard``.  Both regular and HTMX requests are handled.
    """
    # Create a fresh client for auth (avoid cached client issues in serverless)
    from supabase import create_client as _create

    supabase = _create(settings.supabase_url, settings.supabase_anon_key)

    try:
        auth_response = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except Exception as exc:
        logger.warning("login_failed", email=email, error=str(exc))
        return _login_error_response(request, "メールアドレスまたはパスワードが正しくありません。")

    session = auth_response.session
    if session is None:
        logger.warning("login_no_session", email=email)
        return _login_error_response(
            request, "Authentication failed. Please try again."
        )

    access_token: str = session.access_token
    refresh_token: str = session.refresh_token

    # Build response depending on request type
    if _is_htmx(request):
        response = HTMLResponse(content="", status_code=200)
        response.headers["HX-Redirect"] = "/dashboard"
    else:
        response = RedirectResponse(url="/dashboard", status_code=302)

    _set_auth_cookies(response, access_token, refresh_token)

    logger.info("login_success", email=email)
    return response


def _login_error_response(request: Request, message: str) -> Response:
    """Return an error response appropriate for the request type."""
    if _is_htmx(request):
        html = (
            '<div id="login-error" class="alert alert-error" role="alert">'
            f"{message}"
            "</div>"
        )
        return HTMLResponse(content=html, status_code=200)

    # For a regular request redirect back to login with an error query param.
    return RedirectResponse(
        url=f"/login?error={message}",
        status_code=302,
    )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Sign the user out by clearing auth cookies.

    Attempts to invalidate the Supabase session as well (best-effort).
    """
    try:
        supabase = get_supabase_client()
        supabase.auth.sign_out()
    except Exception:
        # Best-effort; cookie removal is what matters.
        pass

    if _is_htmx(request):
        response = HTMLResponse(content="", status_code=200)
        response.headers["HX-Redirect"] = "/login"
    else:
        response = RedirectResponse(url="/login", status_code=302)

    _clear_auth_cookies(response)

    logger.info("logout")
    return response


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@router.get("/me")
async def me(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the currently authenticated user's basic information."""
    return current_user


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post("/refresh")
async def refresh(
    request: Request,
    refresh_token: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Exchange a refresh token (from cookie) for a new access token.

    The new JWT pair is written back to cookies.
    """
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided",
        )

    supabase = get_supabase_client()

    try:
        auth_response = supabase.auth.refresh_session(refresh_token)
    except Exception as exc:
        logger.warning("refresh_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to refresh session",
        ) from exc

    session = auth_response.session
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to refresh session",
        )

    new_access: str = session.access_token
    new_refresh: str = session.refresh_token

    response = JSONResponse(content={"status": "ok"})
    _set_auth_cookies(response, new_access, new_refresh)

    logger.info("token_refreshed")
    return response
