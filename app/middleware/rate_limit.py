"""Shared SlowAPI limiter instance.

Used to decorate sensitive auth endpoints (login, forgot-password) with
per-IP rate limits.  The limiter is registered with the FastAPI app inside
``app.main.create_app`` so the ``@limiter.limit(...)`` decorators take effect.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# Single shared limiter – import this from endpoint modules to apply rules.
limiter = Limiter(key_func=get_remote_address)
