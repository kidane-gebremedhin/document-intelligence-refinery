# Unit tests for shared value objects (spec 07 §2).
# Task: P1-T001 — BoundingBox, PageRef, PageSpan, LanguageCode, DocumentClass.

import pytest
from pydantic import BaseModel, ValidationError

from src.models import BoundingBox, DocumentClass, LanguageCode, PageRef, PageSpan


# -----------------------------------------------------------------------------
# BoundingBox invariants (x0 < x1, y0 < y1)
# -----------------------------------------------------------------------------


def test_bounding_box_valid():
    """Valid box: x0 < x1 and y0 < y1."""
    b = BoundingBox(x0=10.0, y0=20.0, x1=100.0, y1=200.0)
    assert b.x0 == 10.0 and b.x1 == 100.0
    assert b.y0 == 20.0 and b.y1 == 200.0
    assert b.x0 < b.x1 and b.y0 < b.y1


def test_bounding_box_rejects_x1_le_x0():
    """x1 must be greater than x0."""
    with pytest.raises(ValidationError) as exc_info:
        BoundingBox(x0=50.0, y0=20.0, x1=50.0, y1=200.0)
    assert "x1" in str(exc_info.value).lower() or "greater" in str(exc_info.value).lower()

    with pytest.raises(ValidationError):
        BoundingBox(x0=100.0, y0=20.0, x1=10.0, y1=200.0)


def test_bounding_box_rejects_y1_le_y0():
    """y1 must be greater than y0."""
    with pytest.raises(ValidationError) as exc_info:
        BoundingBox(x0=10.0, y0=200.0, x1=100.0, y1=200.0)
    assert "y1" in str(exc_info.value).lower() or "greater" in str(exc_info.value).lower()

    with pytest.raises(ValidationError):
        BoundingBox(x0=10.0, y0=200.0, x1=100.0, y1=20.0)


# -----------------------------------------------------------------------------
# PageRef invariants (page_number >= 1)
# -----------------------------------------------------------------------------


def test_page_ref_valid():
    """Valid PageRef: page_number >= 1."""
    r = PageRef(document_id="doc-1", page_number=1)
    assert r.document_id == "doc-1" and r.page_number == 1

    r2 = PageRef(document_id="doc-2", page_number=999)
    assert r2.page_number == 999


def test_page_ref_rejects_page_zero_or_negative():
    """page_number must be >= 1."""
    with pytest.raises(ValidationError):
        PageRef(document_id="doc-1", page_number=0)
    with pytest.raises(ValidationError):
        PageRef(document_id="doc-1", page_number=-1)


# -----------------------------------------------------------------------------
# PageSpan invariants (page_start >= 1, page_end >= page_start)
# -----------------------------------------------------------------------------


def test_page_span_valid():
    """Valid PageSpan: page_start >= 1, page_end >= page_start."""
    s = PageSpan(document_id="doc-1", page_start=1, page_end=5)
    assert s.page_start == 1 and s.page_end == 5

    s2 = PageSpan(document_id="doc-2", page_start=3, page_end=3)
    assert s2.page_start == s2.page_end == 3


def test_page_span_rejects_page_end_less_than_page_start():
    """page_end must be >= page_start."""
    with pytest.raises(ValidationError) as exc_info:
        PageSpan(document_id="doc-1", page_start=5, page_end=2)
    assert "page_end" in str(exc_info.value).lower() or "page_start" in str(exc_info.value).lower()


def test_page_span_rejects_page_start_zero_or_negative():
    """page_start and page_end must be >= 1 (Field(ge=1))."""
    with pytest.raises(ValidationError):
        PageSpan(document_id="doc-1", page_start=0, page_end=1)
    with pytest.raises(ValidationError):
        PageSpan(document_id="doc-1", page_start=1, page_end=0)


# -----------------------------------------------------------------------------
# LanguageCode and DocumentClass (smoke)
# -----------------------------------------------------------------------------


def test_language_code_valid():
    """LanguageCode accepts 2–5 lowercase letters."""
    class M(BaseModel):
        lang: LanguageCode

    m = M(lang="en")
    assert m.lang == "en"
    m2 = M(lang="EN")
    assert m2.lang == "en"
    m3 = M(lang="am")
    assert m3.lang == "am"


def test_language_code_rejects_invalid():
    """LanguageCode rejects wrong length or non-alpha."""
    class M(BaseModel):
        lang: LanguageCode

    with pytest.raises(ValidationError):
        M(lang="e")
    with pytest.raises(ValidationError):
        M(lang="toolong")
    with pytest.raises(ValidationError):
        M(lang="en1")


def test_document_class_enum():
    """DocumentClass has expected values and serializes to spec strings."""
    assert DocumentClass.FAST_TEXT_SUFFICIENT.value == "fast_text_sufficient"
    assert DocumentClass.NEEDS_LAYOUT_MODEL.value == "needs_layout_model"
    assert DocumentClass.NEEDS_VISION_MODEL.value == "needs_vision_model"
