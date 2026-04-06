from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import get_current_user
from app.main import templates

router = APIRouter(tags=["pages"])


def _is_htmx(request: Request) -> bool:
    """Return ``True`` when the request comes from htmx (HX-Request header)."""
    return request.headers.get("HX-Request", "").lower() == "true"


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------


@router.get("/", response_class=RedirectResponse)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    template_name = (
        "pages/login.html" if not _is_htmx(request) else "partials/login.html"
    )
    return templates.TemplateResponse(template_name, {"request": request})


# ---------------------------------------------------------------------------
# Authenticated pages
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    template_name = (
        "pages/dashboard.html"
        if not _is_htmx(request)
        else "partials/dashboard.html"
    )
    return templates.TemplateResponse(
        template_name, {"request": request, "user": current_user}
    )


@router.get("/simulation/new", response_class=HTMLResponse)
async def simulation_new_page(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    template_name = (
        "pages/simulation.html"
        if not _is_htmx(request)
        else "partials/simulation.html"
    )
    return templates.TemplateResponse(
        template_name, {"request": request, "user": current_user}
    )


@router.get("/simulation/{simulation_id}/result", response_class=HTMLResponse)
async def simulation_result_page(
    request: Request,
    simulation_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    template_name = (
        "pages/simulation_result.html"
        if not _is_htmx(request)
        else "partials/simulation_result.html"
    )
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "user": current_user,
            "simulation_id": simulation_id,
        },
    )


@router.get("/market-data", response_class=HTMLResponse)
async def market_data_list_page(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    template_name = (
        "pages/market_data_list.html"
        if not _is_htmx(request)
        else "partials/market_data_list.html"
    )
    return templates.TemplateResponse(
        template_name, {"request": request, "user": current_user}
    )


@router.get("/market-data/{item_id}", response_class=HTMLResponse)
async def market_data_detail_page(
    request: Request,
    item_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    template_name = (
        "pages/market_data_detail.html"
        if not _is_htmx(request)
        else "partials/market_data_detail.html"
    )
    return templates.TemplateResponse(
        template_name,
        {"request": request, "user": current_user, "item_id": item_id},
    )
