"""Vercel serverless entry point."""
import sys
import traceback

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Module-level `app` placeholder — Vercel's build step scans the top of this
# file for a top-level `app`/`application`/`handler` symbol; we assign it
# unconditionally so the parse succeeds, then overwrite it if the real import
# works.
app = FastAPI()
_import_error_tb = None

try:
    from app.main import app as _real_app  # noqa: E402

    app = _real_app
except Exception:  # pragma: no cover -- surfaces real traceback to Vercel logs
    _import_error_tb = traceback.format_exc()
    print("=== api/index.py failed to import app.main ===", file=sys.stderr, flush=True)
    print(_import_error_tb, file=sys.stderr, flush=True)

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    )
    async def _fallback(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "app.main import failed",
                "traceback": (_import_error_tb or "").splitlines(),
            },
        )


handler = app
