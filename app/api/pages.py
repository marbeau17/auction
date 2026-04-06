from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt

from app.config import Settings, get_settings

router = APIRouter(tags=["pages"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


async def _get_optional_user(
    access_token: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any] | None:
    """Try to extract user from JWT cookie. Returns None instead of raising 401."""
    if not access_token:
        return None
    try:
        payload: dict[str, Any] = jwt.decode(
            access_token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        user_id = payload.get("sub")
        if not user_id:
            return None
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": payload.get("role", "authenticated"),
        }
    except JWTError:
        return None


def _require_auth(user: dict | None, request: Request):
    """Redirect to login if user is not authenticated."""
    if user is None:
        if _is_htmx(request):
            from fastapi.responses import Response
            resp = Response(status_code=200)
            resp.headers["HX-Redirect"] = "/login"
            return resp
        return RedirectResponse(url="/login", status_code=302)
    return None


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------


@router.get("/", response_class=RedirectResponse)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Import here to avoid circular import
    from app.main import templates
    return templates.TemplateResponse("pages/login.html", {"request": request})


# ---------------------------------------------------------------------------
# Authenticated pages
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: dict[str, Any] | None = Depends(_get_optional_user),
):
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    from app.main import templates
    return templates.TemplateResponse(
        "pages/dashboard.html", {"request": request, "user": user}
    )


@router.get("/simulation/new", response_class=HTMLResponse)
async def simulation_new_page(
    request: Request,
    user: dict[str, Any] | None = Depends(_get_optional_user),
):
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    from app.main import templates
    return templates.TemplateResponse(
        "pages/simulation.html", {"request": request, "user": user}
    )


@router.get("/simulation/{simulation_id}/result", response_class=HTMLResponse)
async def simulation_result_page(
    request: Request,
    simulation_id: str,
    user: dict[str, Any] | None = Depends(_get_optional_user),
):
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    from app.main import templates
    return templates.TemplateResponse(
        "pages/simulation_result.html",
        {"request": request, "user": user, "simulation_id": simulation_id},
    )


@router.get("/market-data", response_class=HTMLResponse)
async def market_data_list_page(
    request: Request,
    user: dict[str, Any] | None = Depends(_get_optional_user),
):
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    from app.main import templates
    return templates.TemplateResponse(
        "pages/market_data_list.html", {"request": request, "user": user}
    )


@router.get("/market-data/{item_id}", response_class=HTMLResponse)
async def market_data_detail_page(
    request: Request,
    item_id: str,
    user: dict[str, Any] | None = Depends(_get_optional_user),
):
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    from app.main import templates
    return templates.TemplateResponse(
        "pages/market_data_detail.html",
        {"request": request, "user": user, "item_id": item_id},
    )
