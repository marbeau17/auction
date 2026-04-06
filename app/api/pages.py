from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings

router = APIRouter(tags=["pages"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _render(request: Request, template: str, context: dict | None = None):
    from app.main import templates

    ctx = context or {}
    return templates.TemplateResponse(request, template, ctx)


async def _get_optional_user(request: Request) -> dict[str, Any] | None:
    """Try to get current user from JWT cookie. Returns None on failure."""
    settings = get_settings()
    access_token = request.cookies.get("access_token")
    if not access_token:
        return None
    try:
        from jose import jwt
        from app.dependencies import _get_jwks

        header = jwt.get_unverified_header(access_token)
        alg = header.get("alg", "HS256")

        if alg == "ES256":
            jwks = _get_jwks(settings.supabase_url)
            payload = jwt.decode(access_token, jwks, algorithms=["ES256"], audience="authenticated")
        else:
            payload = jwt.decode(access_token, settings.supabase_jwt_secret, algorithms=["HS256"], options={"verify_aud": False})

        user_id = payload.get("sub")
        if not user_id:
            return None
        user_meta = payload.get("user_metadata", {})
        return {
            "id": user_id,
            "email": payload.get("email"),
            "role": user_meta.get("role", payload.get("role", "authenticated")),
        }
    except Exception:
        return None


def _require_auth(user: dict | None, request: Request):
    if user is None:
        if _is_htmx(request):
            from fastapi.responses import Response

            resp = Response(status_code=200)
            resp.headers["HX-Redirect"] = "/login"
            return resp
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/", response_class=RedirectResponse)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render(request, "pages/login.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    return _render(request, "pages/dashboard.html", {"user": user})


@router.get("/simulation/new", response_class=HTMLResponse)
async def simulation_new_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    return _render(request, "pages/simulation.html", {"user": user})


@router.get("/simulation/{simulation_id}/result", response_class=HTMLResponse)
async def simulation_result_page(request: Request, simulation_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    return _render(request, "pages/simulation_result.html", {"user": user, "simulation_id": simulation_id})


@router.get("/market-data", response_class=HTMLResponse)
async def market_data_list_page(request: Request):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    return _render(request, "pages/market_data_list.html", {"user": user})


@router.get("/market-data/{item_id}", response_class=HTMLResponse)
async def market_data_detail_page(request: Request, item_id: str):
    user = await _get_optional_user(request)
    redirect = _require_auth(user, request)
    if redirect:
        return redirect
    return _render(request, "pages/market_data_detail.html", {"user": user, "item_id": item_id})
