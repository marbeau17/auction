from __future__ import annotations

from urllib.parse import quote


def content_disposition(filename: str) -> str:
    """Build an ``attachment`` ``Content-Disposition`` header safe for non-ASCII filenames.

    Starlette encodes response headers as latin-1, so a raw Japanese filename
    crashes the response. Emit both an ASCII ``filename=`` fallback and an
    RFC 5987 UTF-8-encoded ``filename*`` so modern clients get the original name
    and legacy ones still receive something printable.
    """
    encoded = quote(filename, safe="")
    ascii_fallback = (
        filename.encode("ascii", errors="replace").decode("ascii").replace("?", "_")
    )
    if not ascii_fallback.strip("_"):
        ascii_fallback = "download"
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
