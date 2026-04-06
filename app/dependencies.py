from __future__ import annotations

import json
from typing import Any, Callable

import httpx
from cachetools import TTLCache
from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt

from app.config import Settings, get_settings

# Cache JWKS for 1 hour
_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


def _get_jwks(supabase_url: str) -> dict:
    """Fetch JWKS from Supabase and cache it."""
    cache_key = "jwks"
    if cache_key in _jwks_cache:
        return _jwks_cache[cache_key]

    jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
    resp = httpx.get(jwks_url, timeout=10)
    resp.raise_for_status()
    jwks = resp.json()
    _jwks_cache[cache_key] = jwks
    return jwks


def get_supabase_client(
    settings: Settings = Depends(get_settings),
):
    """Return a Supabase client configured with the service-role key."""
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Extract and verify a JWT from the ``access_token`` cookie.

    Supports both ES256 (Supabase default) and HS256 (legacy) tokens.
    Returns a dict with ``id``, ``email``, and ``role`` on success.
    Raises 401 if the token is missing or invalid.
    """
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        # Peek at the header to determine algorithm
        header = jwt.get_unverified_header(access_token)
        alg = header.get("alg", "HS256")

        if alg == "ES256":
            # Verify with Supabase JWKS (asymmetric)
            jwks = _get_jwks(settings.supabase_url)
            payload: dict[str, Any] = jwt.decode(
                access_token,
                jwks,
                algorithms=["ES256"],
                audience="authenticated",
            )
        else:
            # Fallback to HS256 with JWT secret (symmetric)
            payload = jwt.decode(
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
    # Role from user_metadata or top-level
    user_meta = payload.get("user_metadata", {})
    role: str = user_meta.get("role", payload.get("role", "authenticated"))

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    return {"id": user_id, "email": email, "role": role}


def require_role(roles: list[str]) -> Callable[..., dict[str, Any]]:
    """Dependency factory that restricts access to users with specified roles."""

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
