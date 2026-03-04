# Unit tests for ChunkValidator. Task: P3-T004.

import pytest

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.chunking import ChunkValidator, ChunkValidationError, ValidationResult


def _page_ref(doc_id: str = "doc1", page: int = 1) -> PageRef:
    return PageRef(document_id=doc_id, page_number=page)


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)


def _valid_ldu(
    id_: str = "ldu_1",
    content_type: LDUContentType = LDUContentType.PARAGRAPH,
    text: str = "Hello",
    page_refs: list[PageRef] | None = None,
    bounding_boxes: list[BoundingBox] | None = None,
    parent_section_id: str | None = None,
    raw_payload: dict | None = None,
) -> LDU:
    page_refs = page_refs or [_page_ref()]
    bounding_boxes = bounding_boxes or [_bbox()]
    raw_payload = raw_payload or {}
    return LDU(
        id=id_,
        document_id="doc1",
        content_type=content_type,
        text=text,
        raw_payload=raw_payload,
        page_refs=page_refs,
        bounding_boxes=bounding_boxes,
        parent_section_id=parent_section_id,
        token_count=2,
        content_hash=compute_content_hash(content_type.value, text, raw_payload or None),
    )


# -----------------------------------------------------------------------------
# Valid list passes
# -----------------------------------------------------------------------------


def test_validator_accepts_valid_ldus():
    """ChunkValidator accepts a valid list of LDUs and returns success."""
    ldus = [
        _valid_ldu("ldu_1", text="Intro"),
        _valid_ldu("ldu_2", text="Body"),
    ]
    validator = ChunkValidator()
    result = validator.validate(ldus)
    assert result.success is True
    assert result.ldus == ldus
    assert result.errors == []


def test_validator_accepts_empty_list():
    """ChunkValidator accepts empty list."""
    result = ChunkValidator().validate([])
    assert result.success is True
    assert result.ldus == []


# -----------------------------------------------------------------------------
# Rule 1: Table split (header-only followed by body-only)
# -----------------------------------------------------------------------------


def test_validator_rejects_split_table_header_and_body():
    """List with table header-only LDU followed by table body-only LDU → validator rejects."""
    header_only = _valid_ldu(
        "t1_header",
        content_type=LDUContentType.TABLE,
        text="",
        raw_payload={"header": ["A", "B"], "rows": []},
    )
    body_only = _valid_ldu(
        "t1_body",
        content_type=LDUContentType.TABLE,
        text="",
        raw_payload={"rows": [[1, 2], [3, 4]]},
    )
    ldus = [header_only, body_only]
    validator = ChunkValidator()
    result = validator.validate(ldus)
    assert result.success is False
    assert any("Chunking rule 1" in e for e in result.errors)
    assert any("table split" in e.lower() for e in result.errors)
    assert any("header only" in e.lower() for e in result.errors)
    assert any("rows only" in e.lower() for e in result.errors)


# -----------------------------------------------------------------------------
# Rule 2: Figure without caption
# -----------------------------------------------------------------------------


def test_validator_rejects_figure_without_caption():
    """Figure LDU with no caption (text and raw_payload caption empty) → validator rejects."""
    figure_no_caption = _valid_ldu(
        "fig_1",
        content_type=LDUContentType.FIGURE,
        text="",
        raw_payload={},
    )
    ldus = [figure_no_caption]
    result = ChunkValidator().validate(ldus)
    assert result.success is False
    assert any("Chunking rule 2" in e for e in result.errors)
    assert any("figure" in e.lower() and "caption" in e.lower() for e in result.errors)


def test_validator_accepts_figure_with_caption_in_text():
    """Figure LDU with caption in text passes."""
    fig = _valid_ldu(
        "fig_1",
        content_type=LDUContentType.FIGURE,
        text="Figure 1: Revenue chart",
        raw_payload={},
    )
    result = ChunkValidator().validate([fig])
    assert result.success is True


# -----------------------------------------------------------------------------
# Rule 3: List split mid-item
# -----------------------------------------------------------------------------


def test_validator_rejects_list_split_mid_item():
    """List LDU with raw_payload list_complete=False → validator rejects."""
    list_broken = _valid_ldu(
        "list_1",
        content_type=LDUContentType.LIST,
        text="1. First\n2. Second\n3. Incomplete",
        raw_payload={"list_complete": False},
    )
    result = ChunkValidator().validate([list_broken])
    assert result.success is False
    assert any("Chunking rule 3" in e for e in result.errors)
    assert any("list" in e.lower() and "mid-item" in e.lower() for e in result.errors)


# -----------------------------------------------------------------------------
# Rule 4: Missing section metadata
# -----------------------------------------------------------------------------


def test_validator_rejects_missing_parent_section_after_section_intro():
    """After a section_intro LDU, content LDU without parent_section_id → validator rejects."""
    section = _valid_ldu(
        "sec_1",
        content_type=LDUContentType.SECTION_INTRO,
        text="3. Risk Factors",
        parent_section_id=None,
    )
    paragraph_no_section = _valid_ldu(
        "p_1",
        content_type=LDUContentType.PARAGRAPH,
        text="Some risk factors apply.",
        parent_section_id=None,
    )
    ldus = [section, paragraph_no_section]
    result = ChunkValidator().validate(ldus)
    assert result.success is False
    assert any("Chunking rule 4" in e for e in result.errors)
    assert any("parent_section_id" in e for e in result.errors)


# -----------------------------------------------------------------------------
# Provenance: missing page_refs or content_hash
# -----------------------------------------------------------------------------


def test_validator_rejects_ldu_with_empty_page_refs():
    """LDU with empty page_refs (built via model_construct) → validator rejects."""
    ldu = LDU.model_construct(
        id="ldu_1",
        document_id="doc1",
        content_type=LDUContentType.PARAGRAPH,
        text="Hi",
        page_refs=[],
        bounding_boxes=[_bbox()],
        token_count=1,
        content_hash=compute_content_hash("paragraph", "Hi"),
    )
    result = ChunkValidator().validate([ldu])
    assert result.success is False
    assert any("page_refs" in e and "non-empty" in e for e in result.errors)


def test_validator_rejects_ldu_with_empty_content_hash():
    """LDU with empty content_hash → validator rejects."""
    ldu = LDU.model_construct(
        id="ldu_1",
        document_id="doc1",
        content_type=LDUContentType.PARAGRAPH,
        text="Hi",
        page_refs=[_page_ref()],
        bounding_boxes=[_bbox()],
        token_count=1,
        content_hash="",
    )
    result = ChunkValidator().validate([ldu])
    assert result.success is False
    assert any("content_hash" in e for e in result.errors)


# -----------------------------------------------------------------------------
# validate_or_raise
# -----------------------------------------------------------------------------


def test_validate_or_raise_raises_on_failure():
    """validate_or_raise raises ChunkValidationError with result."""
    validator = ChunkValidator()
    broken = _valid_ldu("fig_1", content_type=LDUContentType.FIGURE, text="", raw_payload={})
    with pytest.raises(ChunkValidationError) as exc_info:
        validator.validate_or_raise([broken])
    assert exc_info.value.result.success is False
    assert "figure" in str(exc_info.value).lower() or "caption" in str(exc_info.value).lower()


def test_validate_or_raise_returns_ldus_on_success():
    """validate_or_raise returns the list when valid."""
    ldus = [_valid_ldu("ldu_1")]
    result = ChunkValidator().validate_or_raise(ldus)
    assert result == ldus
