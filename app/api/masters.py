"""Masters API – CRUD for makers, models, body types, categories, and depreciation curves."""

from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from supabase import Client

from app.db.repositories.master_repo import MasterRepository
from app.dependencies import get_current_user, get_supabase_client, require_role
from app.middleware.rbac import require_permission
from app.models.master import (
    BodyTypeCreate,
    BodyTypeResponse,
    BodyTypeUpdate,
    DepreciationCurveCreate,
    DepreciationCurveResponse,
    MakerCreate,
    MakerResponse,
    ModelCreate,
    ModelResponse,
    VehicleCategoryResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/masters", tags=["masters"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_htmx(request: Request) -> bool:
    """Return True when the request comes from htmx (HX-Request header)."""
    return request.headers.get("HX-Request", "").lower() == "true"


def _get_repo(db: Client = Depends(get_supabase_client)) -> MasterRepository:
    """Dependency that provides a MasterRepository instance."""
    return MasterRepository(db)


def _options_html(items: list[dict[str, Any]], *, placeholder: str = "選択してください") -> str:
    """Build an HTML string of <option> elements for an HTMX response."""
    parts = [f'<option value="">{placeholder}</option>']
    for item in items:
        value = item.get("id", "")
        label = item.get("name", "")
        parts.append(f'<option value="{value}">{label}</option>')
    return "\n".join(parts)


# ===================================================================
# Makers
# ===================================================================


@router.get("/makers", response_model=list[MakerResponse])
async def list_makers(
    request: Request,
    current_user: dict[str, Any] = Depends(require_permission("pricing_masters", "read")),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """List all makers. Returns <option> HTML when called via HTMX."""
    makers: list[dict[str, Any]] = []
    repo_failed = False
    try:
        makers = await repo.list_makers()
    except Exception:
        logger.exception("list_makers_endpoint_failed")
        makers = []
        repo_failed = True

    htmx = _is_htmx(request)

    # Silent fixture fallback — only for HTMX dropdown callers (the simulation
    # form). JSON API consumers (pricing-masters admin UI) keep seeing the
    # authoritative empty response so they can render their own empty-state
    # without a misleading demo payload.
    if htmx and not makers:
        from app.services.sample_data import get_makers as _fx_makers
        makers = _fx_makers()

    # If Supabase raised and the caller wants JSON, preserve the legacy 500.
    if repo_failed and not htmx:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch makers",
        )

    if htmx:
        html = _options_html(makers, placeholder="メーカーを選択")
        return HTMLResponse(content=html)

    return JSONResponse(content={"status": "success", "data": makers})


@router.post(
    "/makers",
    response_model=MakerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_maker(
    body: MakerCreate,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """Create a new maker (admin only)."""
    try:
        created = await repo.create_maker(body.model_dump(exclude_none=True))
    except Exception as exc:
        logger.exception("create_maker_endpoint_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create maker: {exc}",
        )

    return JSONResponse(
        content={"status": "success", "data": created},
        status_code=status.HTTP_201_CREATED,
    )


# ===================================================================
# Models (children of Makers)
# ===================================================================


@router.get("/makers/{maker_id}/models", response_model=list[ModelResponse])
async def list_models(
    maker_id: UUID,
    request: Request,
    current_user: dict[str, Any] = Depends(require_permission("pricing_masters", "read")),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """List models for a given maker. Returns <option> HTML when called via HTMX."""
    try:
        models = await repo.list_models_by_maker(str(maker_id))
    except Exception:
        logger.exception("list_models_endpoint_failed", maker_id=str(maker_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch models",
        )

    if _is_htmx(request):
        html = _options_html(models, placeholder="モデルを選択")
        return HTMLResponse(content=html)

    return JSONResponse(content={"status": "success", "data": models})


@router.post(
    "/makers/{maker_id}/models",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_model(
    maker_id: UUID,
    body: ModelCreate,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """Create a new model under a maker (admin only)."""
    try:
        created = await repo.create_model(
            str(maker_id), body.model_dump(exclude_none=True)
        )
    except Exception as exc:
        logger.exception("create_model_endpoint_failed", maker_id=str(maker_id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create model: {exc}",
        )

    return JSONResponse(
        content={"status": "success", "data": created},
        status_code=status.HTTP_201_CREATED,
    )


# ===================================================================
# Body Types
# ===================================================================


@router.get("/body-types", response_model=list[BodyTypeResponse])
async def list_body_types(
    request: Request,
    current_user: dict[str, Any] = Depends(require_permission("pricing_masters", "read")),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """List all body types. Returns <option> HTML when called via HTMX."""
    body_types: list[dict[str, Any]] = []
    repo_failed = False
    try:
        body_types = await repo.list_body_types()
    except Exception:
        logger.exception("list_body_types_endpoint_failed")
        body_types = []
        repo_failed = True

    htmx = _is_htmx(request)

    # Fixture fallback only for HTMX dropdown callers — keep the JSON admin
    # CRUD contract (empty → 200 []; failure → 500) intact.
    if htmx and not body_types:
        from app.services.sample_data import get_body_types as _fx_body_types
        body_types = _fx_body_types()

    if repo_failed and not htmx:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch body types",
        )

    if htmx:
        html = _options_html(body_types, placeholder="ボディタイプを選択")
        return HTMLResponse(content=html)

    return JSONResponse(content={"status": "success", "data": body_types})


@router.post(
    "/body-types",
    response_model=BodyTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_body_type(
    body: BodyTypeCreate,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """Create a new body type (admin only)."""
    try:
        created = await repo.create_body_type(body.model_dump(exclude_none=True))
    except Exception as exc:
        logger.exception("create_body_type_endpoint_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create body type: {exc}",
        )

    return JSONResponse(
        content={"status": "success", "data": created},
        status_code=status.HTTP_201_CREATED,
    )


@router.put("/body-types/{body_type_id}", response_model=BodyTypeResponse)
async def update_body_type(
    body_type_id: UUID,
    body: BodyTypeUpdate,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """Update a body type (admin only)."""
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    try:
        updated = await repo.update_body_type(str(body_type_id), update_data)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Body type {body_type_id} not found",
        )
    except Exception as exc:
        logger.exception("update_body_type_endpoint_failed", id=str(body_type_id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update body type: {exc}",
        )

    return JSONResponse(content={"status": "success", "data": updated})


@router.delete("/body-types/{body_type_id}", status_code=status.HTTP_200_OK)
async def delete_body_type(
    body_type_id: UUID,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """Soft-delete a body type by setting is_active=False (admin only)."""
    try:
        deleted = await repo.soft_delete_body_type(str(body_type_id))
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Body type {body_type_id} not found",
        )
    except Exception as exc:
        logger.exception("delete_body_type_endpoint_failed", id=str(body_type_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete body type: {exc}",
        )

    return JSONResponse(
        content={"status": "success", "data": deleted, "message": "Body type deactivated"}
    )


# ===================================================================
# Vehicle Categories
# ===================================================================


@router.get("/categories", response_model=list[VehicleCategoryResponse])
async def list_categories(
    current_user: dict[str, Any] = Depends(require_permission("pricing_masters", "read")),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """List all vehicle categories.

    No fixture fallback here — the JSON contract is used by the
    pricing-masters admin UI. The simulation form reads categories via the
    server-rendered page context (``/simulation/new``) which has its own
    fixture fallback in ``app/api/pages.py``.
    """
    try:
        categories = await repo.list_vehicle_categories()
    except Exception:
        logger.exception("list_categories_endpoint_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch categories",
        )

    return JSONResponse(content={"status": "success", "data": categories})


# ===================================================================
# Depreciation Curves
# ===================================================================


@router.get("/depreciation-curves", response_model=list[DepreciationCurveResponse])
async def list_depreciation_curves(
    category_id: Optional[UUID] = Query(default=None, description="Filter by category ID"),
    current_user: dict[str, Any] = Depends(require_permission("pricing_masters", "read")),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """List depreciation curves, optionally filtered by category_id."""
    try:
        curves = await repo.list_depreciation_curves(
            category_id=str(category_id) if category_id else None
        )
    except Exception:
        logger.exception("list_depreciation_curves_endpoint_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch depreciation curves",
        )

    return JSONResponse(content={"status": "success", "data": curves})


@router.get("/models-by-maker")
async def get_models_by_maker(maker: str = "", maker_name: str = ""):
    """Return <option> elements for models of a given maker.

    Accepts either ``?maker=`` (used by the simulation.html HTMX include —
    ``hx-include="[name='maker']"`` serialises the dropdown's ``name`` attr)
    or ``?maker_name=`` (legacy callers / direct API consumers). Falls back
    to the bundled fixture when Supabase returns nothing.
    """
    from app.db.supabase_client import get_supabase_client

    requested = maker or maker_name or ""
    model_names: list[str] = []

    if requested:
        try:
            client = get_supabase_client(service_role=True)
            mfr = (
                client.table("manufacturers")
                .select("id")
                .eq("name", requested)
                .maybe_single()
                .execute()
            )
            if mfr.data:
                models = (
                    client.table("vehicle_models")
                    .select("name")
                    .eq("manufacturer_id", mfr.data["id"])
                    .eq("is_active", True)
                    .order("display_order")
                    .execute()
                )
                model_names = [m["name"] for m in (models.data or []) if m.get("name")]
        except Exception:
            logger.exception("models_by_maker_fetch_failed", maker=requested)
            model_names = []

        # Silent fixture fallback — kicks in whenever Supabase is empty /
        # unreachable / returned no manufacturer match.
        if not model_names:
            from app.services.sample_data import get_models_by_maker as _fx_models
            model_names = [m["name"] for m in _fx_models(requested) if m.get("name")]

    html = '<option value="">車種を選択してください</option>\n'
    for name in model_names:
        html += f'<option value="{name}">{name}</option>\n'
    html += '<option value="__custom__">その他（手動入力）</option>'

    return HTMLResponse(html)


@router.post(
    "/depreciation-curves",
    response_model=DepreciationCurveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_or_update_depreciation_curve(
    body: DepreciationCurveCreate,
    admin_user: dict[str, Any] = Depends(require_role(["admin"])),
    repo: MasterRepository = Depends(_get_repo),
) -> Any:
    """Create or update a depreciation curve point (admin only).

    If a curve point for the same (category_id, year) already exists it will be
    updated; otherwise a new record is inserted.
    """
    data = body.model_dump(exclude_none=True)
    # Ensure UUID is serialised as string for Supabase
    data["category_id"] = str(data["category_id"])

    try:
        result = await repo.upsert_depreciation_curve(data)
    except Exception as exc:
        logger.exception("upsert_depreciation_curve_endpoint_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create/update depreciation curve: {exc}",
        )

    return JSONResponse(
        content={"status": "success", "data": result},
        status_code=status.HTTP_201_CREATED,
    )
