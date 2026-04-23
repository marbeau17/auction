"""PDF text extraction for the Finance Assessment feature (Phase-1).

Uses :mod:`pypdf` for pure-Python text-layer extraction. Pure-Python is a
deliberate choice — it keeps the Vercel lambda well under the 50 MB cap and
avoids shipping a Tesseract binary. When the text layer is absent or too
sparse (scanned / image-only 決算書), we do *not* attempt OCR here; we
return ``needs_vision=True`` and let the LLM-extractor send the raw bytes
to Gemini's vision path instead.

The PDF bytes are never logged — 決算書 contents are sensitive.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import structlog

logger = structlog.get_logger()


MIN_TEXT_LEN = 100  # below this, treat as image-only / scanned PDF


class PDFExtractionError(Exception):
    """Raised when the PDF cannot be parsed at all.

    Typical causes: corrupt bytes, encrypted PDFs with a password we can't
    satisfy, or any other :mod:`pypdf` parsing error. Callers should
    translate this to HTTP 422 (unprocessable entity).
    """


@dataclass
class ExtractionResult:
    """Outcome of a PDF text-extraction attempt.

    Attributes:
        text: The concatenated text across all pages, stripped. ``None`` when
            ``needs_vision`` is True (text layer was absent or too sparse).
        needs_vision: True when the text layer was empty or shorter than
            :data:`MIN_TEXT_LEN` characters total. The caller should re-send
            ``pdf_bytes`` through a vision-capable path (e.g. Gemini
            ``inline_data: application/pdf``).
        page_count: Number of pages pypdf reports in the document.
        pdf_bytes: The original PDF bytes, always passed through so the
            LLM-extractor can re-use them for vision mode without the
            caller having to plumb the raw bytes separately.
    """

    text: str | None
    needs_vision: bool
    page_count: int
    pdf_bytes: bytes


def extract(pdf_bytes: bytes) -> ExtractionResult:
    """Extract text from a PDF.

    If the text layer is absent or too sparse (< :data:`MIN_TEXT_LEN`
    characters total), return ``needs_vision=True`` so the caller can send
    the raw bytes to Gemini's vision path instead.

    Raises:
        PDFExtractionError: The PDF is corrupt, encrypted without a
            password, or otherwise unreadable. Callers should translate
            to HTTP 422.
    """
    # Import pypdf lazily so the rest of the app still boots if the wheel
    # is ever missing at runtime (e.g. a partial deploy).
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover — defensive, not unit-tested
        raise PDFExtractionError(f"pypdf not available: {exc}") from exc

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except PdfReadError as exc:
        logger.warning("pdf_extract_parse_error", error=str(exc))
        raise PDFExtractionError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — pypdf raises a mix of types
        # pypdf can raise ValueError / EOFError / struct.error on malformed
        # input. Wrap everything so callers see one exception type.
        logger.warning("pdf_extract_unknown_error", error_type=type(exc).__name__, error=str(exc))
        raise PDFExtractionError(str(exc)) from exc

    # Encrypted PDFs: try empty-password decrypt, matching the design doc.
    # ``reader.decrypt("")`` returns 0 on failure, 1/2 on success.
    if reader.is_encrypted:
        try:
            decrypt_result = reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 — pypdf decrypt variants
            logger.warning("pdf_extract_decrypt_error", error=str(exc))
            raise PDFExtractionError(f"encrypted PDF — password required ({exc})") from exc
        if decrypt_result == 0:
            logger.info("pdf_extract_encrypted_no_password")
            raise PDFExtractionError("encrypted PDF — password required")

    try:
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdf_extract_page_count_error", error=str(exc))
        raise PDFExtractionError(str(exc)) from exc

    # Concatenate text across all pages. Any per-page extraction failure is
    # non-fatal — we treat that page as empty and continue, because a single
    # weird font map shouldn't sink the whole extraction.
    parts: list[str] = []
    for idx, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf_extract_page_text_error", page_index=idx, error=str(exc))
            parts.append("")

    combined = "".join(parts).strip()

    if len(combined) < MIN_TEXT_LEN:
        logger.info(
            "pdf_extract_needs_vision",
            page_count=page_count,
            text_len=len(combined),
            min_text_len=MIN_TEXT_LEN,
        )
        return ExtractionResult(
            text=None,
            needs_vision=True,
            page_count=page_count,
            pdf_bytes=pdf_bytes,
        )

    logger.info(
        "pdf_extract_ok",
        page_count=page_count,
        text_len=len(combined),
    )
    return ExtractionResult(
        text=combined,
        needs_vision=False,
        page_count=page_count,
        pdf_bytes=pdf_bytes,
    )
