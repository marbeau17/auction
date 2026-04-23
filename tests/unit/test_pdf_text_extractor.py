"""Unit tests for :mod:`app.core.pdf_text_extractor`.

We synthesize small PDFs at runtime with :mod:`reportlab` (already a
project optional-dep under ``[project.optional-dependencies.report]``) so
there are no binary fixtures checked into git. If reportlab is missing,
the PDF-building tests are skipped — the corrupt-bytes test still runs.
"""

from __future__ import annotations

from io import BytesIO

import pytest

from app.core.pdf_text_extractor import (
    MIN_TEXT_LEN,
    ExtractionResult,
    PDFExtractionError,
    extract,
)


# ----------------------------------------------------------------------
# Helpers — build tiny PDFs with reportlab
# ----------------------------------------------------------------------


reportlab = pytest.importorskip(
    "reportlab",
    reason="reportlab is required to synthesize test PDFs",
)


def _make_pdf(pages: list[str]) -> bytes:
    """Build a minimal multi-page PDF with the given per-page strings."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import LETTER

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    for text in pages:
        # Draw the text near the top of the page. reportlab will embed a
        # real text layer, so pypdf's extract_text() should recover it.
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return buf.getvalue()


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_extract_returns_text_for_text_layer_pdf() -> None:
    known = (
        "Quarterly report — revenue figures and operating profit. "
        "This sentence is long enough to clear the MIN_TEXT_LEN threshold. "
        "Additional filler so the total length is comfortably above 100 chars."
    )
    assert len(known) > MIN_TEXT_LEN  # sanity
    pdf_bytes = _make_pdf([known])

    result = extract(pdf_bytes)

    assert isinstance(result, ExtractionResult)
    assert result.needs_vision is False
    assert result.text is not None
    # pypdf text extraction can vary in whitespace / kerning; check substring.
    assert "revenue figures" in result.text
    assert "operating profit" in result.text
    assert result.page_count == 1
    assert result.pdf_bytes is pdf_bytes


def test_extract_empty_pdf_sets_needs_vision() -> None:
    # A PDF with a single blank page — no text content.
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import LETTER

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.showPage()  # blank page, no drawString
    c.save()
    pdf_bytes = buf.getvalue()

    result = extract(pdf_bytes)

    assert result.needs_vision is True
    assert result.text is None
    assert result.page_count == 1
    assert result.pdf_bytes is pdf_bytes


def test_extract_whitespace_only_pdf_sets_needs_vision() -> None:
    # A PDF whose only "content" is whitespace — still below the threshold.
    pdf_bytes = _make_pdf(["   \t  "])

    result = extract(pdf_bytes)

    assert result.needs_vision is True
    assert result.text is None


def test_extract_corrupt_bytes_raises() -> None:
    with pytest.raises(PDFExtractionError):
        extract(b"not a pdf at all")


def test_extract_empty_bytes_raises() -> None:
    with pytest.raises(PDFExtractionError):
        extract(b"")


def test_page_count_matches_multi_page_pdf() -> None:
    pages = [
        "First page content with enough characters to pass the threshold trivially. " * 2,
        "Second page content here, also well above the MIN_TEXT_LEN threshold. " * 2,
        "Third page content — finishing the document with more filler text. " * 2,
    ]
    pdf_bytes = _make_pdf(pages)

    result = extract(pdf_bytes)

    assert result.page_count == 3
    assert result.needs_vision is False
    assert result.text is not None
    assert "First page content" in result.text
    assert "Second page content" in result.text
    assert "Third page content" in result.text
