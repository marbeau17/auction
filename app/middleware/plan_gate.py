"""Plan-tier gate for 松限定 routes.

Usage (FastAPI dep)::

    from app.middleware.plan_gate import require_plan
    @router.get("/risk", dependencies=[Depends(require_plan("matsu"))])

For HTML page routes that render via `_render`, the handler instead calls
``ensure_plan_or_redirect(request, user, required)`` which returns a
RedirectResponse to ``/upgrade`` for lower-tier users.

Spec: docs/uiux_migration_spec.md §5.
"""

from __future__ import annotations

from typing import Callable

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.models.user_plan import meets_plan

logger = structlog.get_logger()


def require_plan(required: str) -> Callable:
    """FastAPI dep: raise 402 if current user's plan < required."""

    async def _checker(request: Request) -> dict:
        # Lazy import to avoid circular dep with app.api.pages.
        from app.api.pages import _get_optional_user

        user = await _get_optional_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not meets_plan(user.get("plan"), required):
            logger.warning(
                "plan_gate_denied",
                user_id=user.get("id"),
                user_plan=user.get("plan"),
                required_plan=required,
                path=request.url.path,
            )
            raise HTTPException(
                status_code=402,
                detail=f"このページは {required} プラン以上で利用可能です",
            )
        return user

    return _checker


def ensure_plan_or_redirect(request: Request, user: dict | None, required: str):
    """For page handlers: return a RedirectResponse to /upgrade if plan insufficient.

    Returns None when the user has sufficient plan (handler should continue).
    """
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not meets_plan(user.get("plan"), required):
        logger.info(
            "plan_gate_redirect",
            user_id=user.get("id"),
            user_plan=user.get("plan"),
            required_plan=required,
            path=request.url.path,
        )
        return RedirectResponse(url="/upgrade", status_code=302)
    return None
