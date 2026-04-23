"""Role-Based Access Control middleware for stakeholder-level permissions."""

from __future__ import annotations

import copy
from functools import wraps
from typing import Callable, Optional

import structlog
from fastapi import Depends, HTTPException, Request

from app.dependencies import get_current_user

logger = structlog.get_logger()

# Permission matrix: resource -> action -> list of allowed roles
RBAC_MATRIX: dict[str, dict[str, list[str]]] = {
    "pricing_logic": {
        "read": ["admin", "operator", "asset_manager"],
        "write": ["admin"],
    },
    "market_data": {
        "read": ["admin", "operator", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "simulations": {
        "read": ["admin", "operator", "investor", "end_user", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "financial": {
        "read": ["admin", "operator", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "contracts": {
        "read": [
            "admin",
            "operator",
            "investor",
            "end_user",
            "asset_manager",
            "private_placement_agent",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin", "operator"],
    },
    "invoices": {
        "read": [
            "admin",
            "operator",
            "end_user",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin", "operator"],
    },
    "fund_info": {
        "read": [
            "admin",
            "operator",
            "investor",
            "asset_manager",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin"],
    },
    "vehicle_inventory": {
        "read": ["admin", "operator", "investor", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "dashboard": {
        "read": [
            "admin",
            "operator",
            "investor",
            "asset_manager",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin"],
    },
    "pricing_masters": {
        "read": ["admin", "operator"],
        "write": ["admin"],
    },
    "stakeholders": {
        "read": ["admin", "operator", "asset_manager"],
        "write": ["admin", "operator"],
    },
}

# Fields hidden from specific roles per resource
_SENSITIVE_FIELDS: dict[str, dict[str, list[str]]] = {
    "simulations": {
        "investor": [
            "result.lease.fee_breakdown",
            "result.acquisition.safety_margin_applied",
        ],
        "end_user": [
            "result.lease.fee_breakdown",
            "result.acquisition.safety_margin_applied",
            "result.residual",
        ],
    },
}


def get_user_role(user: dict) -> str:
    """Extract the effective role from user dict.

    Checks stakeholder_role first, falls back to role.
    """
    return user.get("stakeholder_role") or user.get("role", "viewer")


def check_permission(resource: str, action: str, user: dict) -> bool:
    """Check if user has permission for resource+action."""
    role = get_user_role(user)

    # Admin always has access
    if role == "admin":
        return True

    allowed_roles = RBAC_MATRIX.get(resource, {}).get(action, [])
    return role in allowed_roles


def require_permission(resource: str, action: str = "read"):
    """FastAPI dependency that checks RBAC permission.

    Usage::

        @router.get("/endpoint")
        async def endpoint(user=Depends(require_permission("resource", "read"))):
            ...
    """

    async def permission_checker(
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> dict:
        if not check_permission(resource, action, user):
            role = get_user_role(user)
            logger.warning(
                "rbac_access_denied",
                resource=resource,
                action=action,
                user_role=role,
                user_id=user.get("id"),
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    f"権限がありません: {resource} の {action} "
                    f"操作にはアクセス権限が必要です"
                ),
            )
        return user

    return permission_checker


def require_any_role(*roles: str):
    """FastAPI dependency that checks if user has any of the specified roles.

    Usage::

        @router.get("/admin-only")
        async def admin_endpoint(user=Depends(require_any_role("admin", "operator"))):
            ...
    """

    async def role_checker(
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> dict:
        user_role = get_user_role(user)
        if user_role not in roles:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"このページにアクセスするには "
                    f"{', '.join(roles)} のいずれかの権限が必要です"
                ),
            )
        return user

    return role_checker


def get_accessible_resources(user: dict) -> dict[str, list[str]]:
    """Get all resources and actions accessible to a user.

    Returns a mapping of ``{resource: [allowed_actions]}``.
    Useful for the UI to show/hide elements based on the caller's role.
    """
    role = get_user_role(user)
    accessible: dict[str, list[str]] = {}

    for resource, actions in RBAC_MATRIX.items():
        allowed_actions = []
        for action, allowed_roles in actions.items():
            if role in allowed_roles or role == "admin":
                allowed_actions.append(action)
        if allowed_actions:
            accessible[resource] = allowed_actions

    return accessible


def filter_response_fields(data: dict, resource: str, user: dict) -> dict:
    """Filter sensitive fields from response based on user's role.

    For example, pricing logic details should not be visible to investors.
    Nested field paths use dot notation (e.g. ``result.lease.fee_breakdown``).
    """
    role = get_user_role(user)

    hidden_fields = _SENSITIVE_FIELDS.get(resource, {}).get(role, [])
    if not hidden_fields:
        return data

    # Deep copy so callers keep the original intact
    filtered = copy.deepcopy(data)
    for field_path in hidden_fields:
        parts = field_path.split(".")
        obj = filtered
        for part in parts[:-1]:
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                break
        else:
            if isinstance(obj, dict):
                obj.pop(parts[-1], None)

    return filtered
