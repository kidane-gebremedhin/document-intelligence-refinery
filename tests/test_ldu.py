# Unit tests for LDU model and content_hash. Task: P3-T001.

import pytest
from pydantic import ValidationError

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    canonicalize_text,
    canonicalize_raw_payload,
    compute_content_hash,
)


def _page_ref(document_id: str = "doc1", page_number: int = 1) -> PageRef:
    return PageRef(document_id=document_id, page_number=page_number)


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)


# -----------------------------------------------------------------------------
# content_hash stability
# -----------------------------------------------------------------------------


def test_same_canonical_content_same_hash():
    """Same normalized content hashed twice yields the same content_hash."""
    h1 = compute_content_hash("paragraph", "Hello world")
    h2 = compute_content_hash("paragraph", "Hello world")
    assert h1 == h2
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


def test_different_content_different_hash():
    """Different content yields different hash."""
    h1 = compute_content_hash("paragraph", "Hello")
    h2 = compute_content_hash("paragraph", "World")
    assert h1 != h2


def test_different_content_type_different_hash():
    """Same text but different content_type yields different hash (stable identifiers)."""
    h1 = compute_content_hash("paragraph", "Summary")
    h2 = compute_content_hash("section_intro", "Summary")
    assert h1 != h2


def test_whitespace_normalization_same_hash():
    """Whitespace-normalized content yields the same hash as original after normalization."""
    raw = "  Hello   world\n\n  again  "
    normalized = canonicalize_text(raw)
    assert normalized == "Hello world again"
    h_raw = compute_content_hash("paragraph", raw)
    h_normalized = compute_content_hash("paragraph", normalized)
    assert h_raw == h_normalized


def test_extra_spaces_collapsed_same_hash():
    """Extra spaces collapsed to one space yields same hash."""
    h1 = compute_content_hash("paragraph", "a b c")
    h2 = compute_content_hash("paragraph", "a  b   c")
    assert h1 == h2


def test_canonicalize_text_trim_and_collapse():
    """canonicalize_text trims and collapses whitespace."""
    assert canonicalize_text("  x  y  ") == "x y"
    assert canonicalize_text("\n\t  line1 \n line2  ") == "line1 line2"
    assert canonicalize_text("") == ""


def test_raw_payload_canonical_serialization():
    """Tables: canonical JSON (sorted keys) so key order does not change hash."""
    payload_a = {"rows": [[1, 2]], "cols": ["A", "B"]}
    payload_b = {"cols": ["A", "B"], "rows": [[1, 2]]}
    h1 = compute_content_hash("table", "Table 1", payload_a)
    h2 = compute_content_hash("table", "Table 1", payload_b)
    assert h1 == h2
    assert canonicalize_raw_payload(payload_a) == canonicalize_raw_payload(payload_b)


def test_content_hash_excludes_page_and_bbox():
    """Hash is content-scoped; changing page/bbox would not be in hash (no API for that here)."""
    h = compute_content_hash("paragraph", "Same text")
    assert h == compute_content_hash("paragraph", "Same text")


# -----------------------------------------------------------------------------
# LDU model validators
# -----------------------------------------------------------------------------


def test_ldu_valid_roundtrip():
    """LDU instantiates with required fields; serialization to JSON round-trips."""
    ldu = LDU(
        id="ldu_1",
        document_id="doc1",
        content_type=LDUContentType.PARAGRAPH,
        text="Hello",
        page_refs=[_page_ref()],
        bounding_boxes=[_bbox()],
        token_count=2,
        content_hash=compute_content_hash("paragraph", "Hello"),
    )
    assert ldu.content_hash
    data = ldu.model_dump(mode="json")
    back = LDU.model_validate(data)
    assert back.id == ldu.id
    assert back.content_hash == ldu.content_hash
    assert len(back.page_refs) == 1
    assert len(back.bounding_boxes) == 1


def test_ldu_rejects_empty_page_refs():
    """LDU rejects when page_refs is empty."""
    with pytest.raises(ValidationError) as exc_info:
        LDU(
            id="ldu_1",
            document_id="doc1",
            content_type=LDUContentType.PARAGRAPH,
            text="Hi",
            page_refs=[],
            bounding_boxes=[_bbox()],
            token_count=1,
            content_hash=compute_content_hash("paragraph", "Hi"),
        )
    assert "page_refs" in str(exc_info.value).lower() or "non-empty" in str(exc_info.value).lower()


def test_ldu_rejects_empty_bounding_boxes():
    """LDU rejects when bounding_boxes is empty."""
    with pytest.raises(ValidationError) as exc_info:
        LDU(
            id="ldu_1",
            document_id="doc1",
            content_type=LDUContentType.PARAGRAPH,
            text="Hi",
            page_refs=[_page_ref()],
            bounding_boxes=[],
            token_count=1,
            content_hash=compute_content_hash("paragraph", "Hi"),
        )
    assert "bounding" in str(exc_info.value).lower() or "non-empty" in str(exc_info.value).lower()


def test_ldu_rejects_empty_content_hash():
    """LDU rejects when content_hash is empty."""
    with pytest.raises(ValidationError):
        LDU(
            id="ldu_1",
            document_id="doc1",
            content_type=LDUContentType.PARAGRAPH,
            text="Hi",
            page_refs=[_page_ref()],
            bounding_boxes=[_bbox()],
            token_count=1,
            content_hash="",
        )
