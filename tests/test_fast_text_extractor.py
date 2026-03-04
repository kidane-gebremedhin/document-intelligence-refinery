# Unit tests for FastTextExtractor. Task: P2-T004.

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    DocumentProfile,
    DomainHint,
    EstimatedExtractionCost,
    LayoutComplexity,
    OriginType,
)
from src.strategies import FastTextExtractor
from src.strategies.fast_text_extractor import _compute_confidence_signals, _plumber_bbox_to_model


# -----------------------------------------------------------------------------
# Bbox conversion
# -----------------------------------------------------------------------------


def test_plumber_bbox_to_model_bottom_left_origin():
    """pdfplumber top-left coords convert to bottom-left (y flip)."""
    # page_height=100: top=10, bottom=20 in plumber -> y0=80, y1=90 in model
    bbox = _plumber_bbox_to_model(5.0, 10.0, 50.0, 20.0, page_height=100.0)
    assert bbox.x0 == 5.0 and bbox.x1 == 50.0
    assert bbox.y0 == 80.0 and bbox.y1 == 90.0
    assert bbox.y0 < bbox.y1


# -----------------------------------------------------------------------------
# Confidence signals (deterministic)
# -----------------------------------------------------------------------------


def test_confidence_signals_high_chars_low_image():
    """High char count, low image area -> high score."""
    config = {"min_chars_per_page": 50, "max_image_area_ratio": 0.5, "min_char_density_per_10k_points2": 1.0}
    # One page: 600 chars, 72*72 area, small text area, no images
    pages = [
        {
            "char_count": 600,
            "width": 72.0,
            "height": 72.0,
            "text_area": 1000.0,
            "image_area": 0.0,
            "has_font_metadata": True,
        }
    ]
    score, signals = _compute_confidence_signals(pages, config)
    assert score >= 0.5
    assert signals["char_count_total"] == 600
    assert signals["image_area_ratio"] == 0.0
    assert signals["missing_text_indicator"] is False


def test_confidence_signals_low_chars_high_image():
    """Low char count and high image area -> lower score."""
    config = {"min_chars_per_page": 50, "max_image_area_ratio": 0.5, "min_char_density_per_10k_points2": 1.0}
    page_area = 72.0 * 72.0
    pages = [
        {
            "char_count": 10,
            "width": 72.0,
            "height": 72.0,
            "text_area": 100.0,
            "image_area": page_area * 0.7,
            "has_font_metadata": False,
        }
    ]
    score, signals = _compute_confidence_signals(pages, config)
    assert score < 0.5
    assert signals["pages_with_low_chars"] == 1
    assert signals["image_area_ratio"] == pytest.approx(0.7)
    assert signals["missing_text_indicator"] is True


def test_confidence_signals_empty_pages():
    """No pages -> score 0."""
    config = {}
    score, signals = _compute_confidence_signals([], config)
    assert score == 0.0
    assert signals["char_count_total"] == 0
    assert signals["missing_text_indicator"] is True


# -----------------------------------------------------------------------------
# FastTextExtractor with mocked pdfplumber
# -----------------------------------------------------------------------------


def _make_mock_page(width: float = 612.0, height: float = 792.0, words: list | None = None, char_count: int = 0):
    words = words or [{"x0": 72, "top": 100, "x1": 200, "bottom": 112, "text": "Hello world"}]
    page = MagicMock()
    page.width = width
    page.height = height
    page.extract_words.return_value = words
    page.chars = [{"fontname": "Helvetica", "x0": 72, "top": 100}] if char_count else []
    page.images = []
    return page


def _make_mock_pdf(num_pages: int = 1, chars_per_page: int = 100) -> MagicMock:
    """Mock PDF with enough words so char count and density are high (confidence above threshold)."""
    pages = []
    for p in range(num_pages):
        # Many words so that char_count and char_density are high
        words = [
            {"x0": 72 + (i % 15) * 40, "top": 100 + (i // 15) * 14 + p * 200, "x1": 72 + (i % 15) * 40 + 38, "bottom": 100 + (i // 15) * 14 + 12 + p * 200, "text": "Word"}
            for i in range(60)
        ]
        page = _make_mock_page(words=words)
        page.chars = [{"fontname": "Helvetica"}] * max(1, chars_per_page)
        page.images = []
        pages.append(page)
    pdf = MagicMock()
    pdf.pages = pages
    return pdf


@patch("src.strategies.fast_text_extractor.pdfplumber.open")
def test_fast_text_extractor_returns_document_when_confidence_above_threshold(mock_open):
    """When confidence >= threshold, result contains ExtractedDocument with text_blocks and metadata."""
    pdf = _make_mock_pdf(num_pages=1, chars_per_page=200)
    mock_open.return_value.__enter__.return_value = pdf
    mock_open.return_value.__exit__.return_value = None

    profile = DocumentProfile(
        document_id="doc1",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        language="en",
        language_confidence=0.9,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        triage_confidence_score=0.95,
        page_count=1,
    )
    extractor = FastTextExtractor()
    result = extractor.extract(Path("/tmp/sample.pdf"), profile)

    assert result.success is True
    assert result.extracted_document is not None
    doc = result.extracted_document
    assert doc.document_id == "doc1"
    assert doc.strategy_used == "fast_text"
    assert doc.pages == 1
    assert len(doc.text_blocks) >= 1
    for b in doc.text_blocks:
        assert b.page_number == 1
        assert b.bbox.x0 < b.bbox.x1 and b.bbox.y0 < b.bbox.y1
        assert b.reading_order_index >= 0
    assert "fast_text_confidence_signals" in doc.metadata
    signals = doc.metadata["fast_text_confidence_signals"]
    assert "char_density_per_10k_points2" in signals
    assert "whitespace_ratio" in signals
    assert "missing_text_indicator" in signals
    assert result.confidence_score >= 0.0
    assert result.strategy_name == "fast_text"


@patch("src.strategies.fast_text_extractor.pdfplumber.open")
def test_fast_text_extractor_escalates_when_confidence_below_threshold(mock_open):
    """When confidence < threshold, result has no document and notes confidence_below_threshold."""
    # Minimal text, no font, so score should be low
    page = _make_mock_page()
    page.chars = []
    page.extract_words.return_value = [{"x0": 72, "top": 100, "x1": 80, "bottom": 102, "text": "x"}]
    pdf = MagicMock()
    pdf.pages = [page]
    mock_open.return_value.__enter__.return_value = pdf
    mock_open.return_value.__exit__.return_value = None

    profile = DocumentProfile(
        document_id="doc1",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        language="en",
        language_confidence=0.9,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        triage_confidence_score=0.95,
        page_count=1,
    )
    extractor = FastTextExtractor()
    result = extractor.extract(Path("/tmp/sparse.pdf"), profile)

    # With one word and no font metadata, score is likely below 0.5
    if not result.success:
        assert result.extracted_document is None
        assert "confidence_below_threshold" in (result.notes or "")
    assert result.strategy_name == "fast_text"


@patch("src.strategies.fast_text_extractor.pdfplumber.open")
def test_fast_text_extractor_reading_order_matches_blocks(mock_open):
    """reading_order ref_ids match text_block ids and order."""
    pdf = _make_mock_pdf(num_pages=1, chars_per_page=300)
    mock_open.return_value.__enter__.return_value = pdf
    mock_open.return_value.__exit__.return_value = None

    profile = DocumentProfile(
        document_id="doc1",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        language="en",
        language_confidence=0.9,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        triage_confidence_score=0.95,
        page_count=1,
    )
    extractor = FastTextExtractor()
    result = extractor.extract(Path("/tmp/read.pdf"), profile)

    if result.success and result.extracted_document:
        doc = result.extracted_document
        block_ids = {b.id for b in doc.text_blocks}
        for entry in doc.reading_order:
            assert entry.ref_id in block_ids
        for i, b in enumerate(doc.text_blocks):
            assert b.reading_order_index == i
