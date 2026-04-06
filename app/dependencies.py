from __future__ import annotations
from typing import Any, Callable

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from supabase import Client, create_client

from app.config import Settings, get_settings


def get_supabase_client(
    settings: Settings = Depends(get_settings),
) -> Client:
    """Return a Supabase client configured with the service-role key."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Extract and verify a JWT from the ``access_token`` cookie.

    Returns a dict with ``id``, ``email``, and ``role`` on success.
    Raises 401 if the token is missing or invalid.
    """
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload: dict[str, Any] = jwt.decode(
            access_token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )

    user_id: str | None = payload.get("sub")
    email: str | None = payload.get("email")
    role: str = payload.get("role", "authenticated")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    return {"id": user_id, "email": email, "role": role}


def require_role(roles: list[str]) -> Callable[..., dict[str, Any]]:
    """Dependency factory that restricts access to users with specified roles.

    Usage::

        @router.get("/admin-only", dependencies=[Depends(require_role(["admin"]))])
        async def admin_view(): ...
    """

    async def _check_role(
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        if current_user.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _check_role
