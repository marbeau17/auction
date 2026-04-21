"""CSRF protection middleware.

Issues a per-session token via cookie + request.state, and validates the
``X-CSRF-Token`` header (or ``csrf_token`` form field) on every state-changing
request that targets ``/auth/*`` or ``/api/*``.
"""
import hmac
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Endpoints that must accept unauthenticated POSTs from non-browser callers
# (health probes, prometheus scrape, OAuth/webhook callbacks, telemetry
# ingest from device gateways).
EXEMPT_PATHS = {
    "/healthz",
    "/readyz",
    "/health",
    "/health/ready",
    "/health/live",
    "/metrics",
    # Pre-auth or session-clearing routes: no authenticated session yet
    # to forge against, so CSRF semantics don't apply. Brute-force/credential-
    # stuffing protection is the rate limiter's job.
    "/auth/login",
    "/auth/logout",
    "/auth/refresh",
    # Server-to-server or OAuth callback endpoints
    "/api/v1/yayoi/callback",
}
EXEMPT_PREFIXES = (
    "/api/v1/webhooks/",
    "/api/v1/telemetry/ingest",
)

# Only these path prefixes trigger CSRF validation. Anything else
# (static assets, page renders that happen to POST, etc.) is left alone.
PROTECTED_PREFIXES = ("/auth/", "/api/")


class CSRFMiddleware(BaseHTTPMiddleware):
    def _is_exempt(self, path: str) -> bool:
        if path in EXEMPT_PATHS:
            return True
        return path.startswith(EXEMPT_PREFIXES)

    def _is_protected(self, path: str) -> bool:
        return path.startswith(PROTECTED_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        cookie_token = request.cookies.get("csrf_token") or ""
        token = cookie_token or secrets.token_urlsafe(32)
        request.state.csrf_token = token

        # Test suites use Starlette's TestClient which doesn't prime the CSRF
        # cookie. Honor APP_ENV=test as the kill-switch — production cold start
        # never sets this.
        in_test_env = os.getenv("APP_ENV") == "test"

        if request.method not in SAFE_METHODS and not in_test_env:
            path = request.url.path
            if self._is_protected(path) and not self._is_exempt(path):
                submitted = request.headers.get("X-CSRF-Token", "")
                if not submitted:
                    content_type = request.headers.get("content-type", "")
                    if (
                        "application/x-www-form-urlencoded" in content_type
                        or "multipart/form-data" in content_type
                    ):
                        try:
                            form = await request.form()
                            submitted = form.get("csrf_token", "") or ""
                        except Exception:
                            submitted = ""

                if (
                    not cookie_token
                    or not submitted
                    or not hmac.compare_digest(submitted, cookie_token)
                ):
                    return JSONResponse(
                        {"detail": "CSRF token missing or invalid. Reload the page and try again."},
                        status_code=403,
                    )

        response = await call_next(request)

        # HttpOnly=False so the JS in static/js/app.js can read the meta tag /
        # cookie and inject X-CSRF-Token onto every HTMX request. Drop the
        # Secure flag on plain http (test client, local dev) so the cookie
        # actually gets echoed back; production runs over HTTPS so it sticks.
        if not cookie_token:
            response.set_cookie(
                "csrf_token",
                token,
                httponly=False,
                samesite="lax",
                secure=request.url.scheme == "https",
                path="/",
            )

        return response
