"""Supabase client factory with instance caching.

Provides cached Supabase client instances for both the anonymous key
(respects RLS) and the service role key (bypasses RLS).
"""

from __future__ import annotations

import threading
from typing import Optional

import structlog
from supabase import Client, create_client

from app.config import get_settings

logger = structlog.get_logger()

_anon_client: Optional[Client] = None
_service_client: Optional[Client] = None
_lock = threading.Lock()


def get_supabase_client(service_role: bool = False) -> Client:
    """Create and return a cached Supabase client instance.

    Args:
        service_role: If True, use the service role key (bypasses RLS).
                      If False, use the anonymous key.

    Returns:
        A supabase.Client instance.

    Raises:
        ValueError: If required configuration values are missing.
    """
    global _anon_client, _service_client

    settings = get_settings()

    if not settings.supabase_url:
        raise ValueError("supabase_url is not configured")

    if service_role:
        if _service_client is not None:
            return _service_client

        if not settings.supabase_service_role_key:
            raise ValueError("supabase_service_role_key is not configured")

        with _lock:
            # Double-check after acquiring lock
            if _service_client is not None:
                return _service_client

            logger.info("creating_supabase_client", role="service_role")
            _service_client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
            return _service_client
    else:
        if _anon_client is not None:
            return _anon_client

        if not settings.supabase_anon_key:
            raise ValueError("supabase_anon_key is not configured")

        with _lock:
            if _anon_client is not None:
                return _anon_client

            logger.info("creating_supabase_client", role="anon")
            _anon_client = create_client(
                settings.supabase_url,
                settings.supabase_anon_key,
            )
            return _anon_client
