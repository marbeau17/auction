"""CSRF protection middleware with strict enforcement.

Note: when ``APP_ENV=test`` (set globally by ``tests/integration/conftest.py``),
the test suite is expected to short-circuit CSRF via the conftest fixtures, so
exemption changes here are effectively production-only.
"""
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

EXEMPT_PATHS = {
    "/auth/callback",
    "/health",
    "/api/v1/yayoi/callback",
}
EXEMPT_PREFIXES = (
    "/api/v1/webhooks/",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    def _is_exempt(self, path: str) -> bool:
        """Check if the path is exempt from CSRF validation."""
        if path in EXEMPT_PATHS:
            return True
        return path.startswith(EXEMPT_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        # Generate token if not in cookie
        csrf_token = request.cookies.get("csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)

        # Make token available to templates via request state
        request.state.csrf_token = csrf_token

        # Validate on state-changing methods (POST, PUT, DELETE, PATCH)
        if request.method not in SAFE_METHODS:
            path = request.url.path
            if not self._is_exempt(path):
                # For HTMX requests, auto-read token from cookie
                # (HTMX sends it via hx-headers configured in base template)
                header_token = request.headers.get("X-CSRF-Token", "")

                # Also accept token from form field for regular form posts
                form_token = ""
                content_type = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                    try:
                        form_data = await request.form()
                        form_token = form_data.get("csrf_token", "")
                    except Exception:
                        form_token = ""

                submitted_token = header_token or form_token
                if not submitted_token or not secrets.compare_digest(submitted_token, csrf_token):
                    return JSONResponse(
                        {"detail": "CSRF token missing or invalid. Reload the page and try again."},
                        status_code=403,
                    )

        response = await call_next(request)

        # Set CSRF cookie on every response so JS/HTMX can read it
        response.set_cookie(
            "csrf_token", csrf_token,
            httponly=False,  # JS needs to read it
            samesite="lax",
            secure=True,
            path="/",
        )

        return response
