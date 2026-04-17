"""Vercel serverless entry point."""
import sys
import traceback

try:
    from app.main import app
except Exception:
    tb = traceback.format_exc()
    print("=== api/index.py failed to import app.main ===", file=sys.stderr, flush=True)
    print(tb, file=sys.stderr, flush=True)

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()
    _error_tb = tb

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _fallback(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "app.main import failed",
                "traceback": _error_tb.splitlines(),
            },
        )

# Vercel looks for `app` (and `handler`) in this module
handler = app
