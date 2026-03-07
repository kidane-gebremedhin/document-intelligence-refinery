# Unit tests for ChunkValidator. Task P3-T002 (P3-T004): 5 rules, error codes, 3+ violations.

import pytest

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.chunking import (
    ChunkValidator,
    ChunkValidationError,
    ChunkValidationErrorItem,
    ValidationResult,
    TABLE_HEADER_CELLS_SPLIT,
    FIGURE_CAPTION_NOT_UNIFIED,
    LIST_MID_ITEM_SPLIT,
    PARENT_SECTION_MISSING,
    PAGE_REFS_EMPTY,
    BOUNDING_BOXES_INVALID,
    CONTENT_HASH_MISSING,
)


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
# Valid list passes (provenance preserved)
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
# Rule 1: Table split (header-only followed by body-only) — TABLE_HEADER_CELLS_SPLIT
# -----------------------------------------------------------------------------


def test_validator_rejects_split_table_header_and_body():
    """List with table header-only LDU followed by table body-only LDU → validator rejects with TABLE_HEADER_CELLS_SPLIT."""
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
    codes = [e.code for e in result.errors]
    assert TABLE_HEADER_CELLS_SPLIT in codes
    assert any("table split" in (e.message or "").lower() for e in result.errors)
    assert any("t1_header" in (e.message or "") and "t1_body" in (e.message or "") for e in result.errors)
    # Provenance: LDUs unchanged
    assert header_only.page_refs and body_only.bounding_boxes


def test_validator_rejects_table_ldu_with_data_only_content():
    """Table LDU whose text content is data-only (no header row) → TABLE_HEADER_CELLS_SPLIT."""
    data_only = _valid_ldu(
        "t1_data",
        content_type=LDUContentType.TABLE,
        text="100\t200\n300\t400",
        raw_payload={},
    )
    result = ChunkValidator().validate([data_only])
    assert result.success is False
    assert any(e.code == TABLE_HEADER_CELLS_SPLIT for e in result.errors)
    assert any("t1_data" in (e.message or "") for e in result.errors)


# -----------------------------------------------------------------------------
# Rule 2: Figure + caption — FIGURE_CAPTION_NOT_UNIFIED
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
    assert any(e.code == FIGURE_CAPTION_NOT_UNIFIED for e in result.errors)
    assert any("figure" in (e.message or "").lower() and "caption" in (e.message or "").lower() for e in result.errors)


def test_validator_rejects_standalone_caption_ldu():
    """Standalone caption LDU (chunk_type caption) → validator rejects with FIGURE_CAPTION_NOT_UNIFIED."""
    caption_only = _valid_ldu(
        "cap_1",
        content_type=LDUContentType.CAPTION,
        text="Figure 2: Revenue by region",
        raw_payload={},
    )
    result = ChunkValidator().validate([caption_only])
    assert result.success is False
    assert any(e.code == FIGURE_CAPTION_NOT_UNIFIED for e in result.errors)
    assert any("Standalone caption" in (e.message or "") or "caption" in (e.message or "").lower() for e in result.errors)
    assert any("cap_1" in (e.message or "") for e in result.errors)


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
# Rule 3: List split mid-item — LIST_MID_ITEM_SPLIT
# -----------------------------------------------------------------------------


def test_validator_rejects_list_split_mid_item():
    """List LDU with raw_payload list_complete=False or text ending mid-item → validator rejects with LIST_MID_ITEM_SPLIT."""
    list_broken = _valid_ldu(
        "list_1",
        content_type=LDUContentType.LIST,
        text="1. First\n2. Second\n3. Incomplete",
        raw_payload={"list_complete": False},
    )
    result = ChunkValidator().validate([list_broken])
    assert result.success is False
    assert any(e.code == LIST_MID_ITEM_SPLIT for e in result.errors)
    assert any("list" in (e.message or "").lower() and "mid-item" in (e.message or "").lower() for e in result.errors)


def test_validator_rejects_numbered_list_ending_mid_item():
    """List LDU whose text ends with incomplete item (no period) → LIST_MID_ITEM_SPLIT."""
    list_incomplete = _valid_ldu(
        "list_2",
        content_type=LDUContentType.LIST,
        text="1. One.\n2. Two.\n3. Incomplete sen",
        raw_payload={},
    )
    result = ChunkValidator().validate([list_incomplete])
    assert result.success is False
    assert any(e.code == LIST_MID_ITEM_SPLIT for e in result.errors)


def test_validator_accepts_complete_list():
    """List LDU with complete items passes."""
    complete_list = _valid_ldu(
        "list_ok",
        content_type=LDUContentType.LIST,
        text="1. First.\n2. Second.\n3. Third.",
        raw_payload={},
    )
    result = ChunkValidator().validate([complete_list])
    assert result.success is True


# -----------------------------------------------------------------------------
# Rule 4: Missing section metadata — PARENT_SECTION_MISSING
# -----------------------------------------------------------------------------


def test_validator_rejects_missing_parent_section_after_section_intro():
    """After a section_intro LDU, content LDU without parent_section_id → validator rejects with PARENT_SECTION_MISSING."""
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
    assert any(e.code == PARENT_SECTION_MISSING for e in result.errors)
    assert any("parent_section_id" in (e.message or "") for e in result.errors)


# -----------------------------------------------------------------------------
# Provenance: PAGE_REFS_EMPTY, BOUNDING_BOXES_INVALID, CONTENT_HASH_MISSING
# -----------------------------------------------------------------------------


def test_validator_rejects_ldu_with_empty_page_refs():
    """LDU with empty page_refs → validator rejects with PAGE_REFS_EMPTY."""
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
    assert any(e.code == PAGE_REFS_EMPTY for e in result.errors)
    assert any("page_refs" in (e.message or "") for e in result.errors)


def test_validator_rejects_ldu_with_empty_content_hash():
    """LDU with empty content_hash → validator rejects with CONTENT_HASH_MISSING."""
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
    assert any(e.code == CONTENT_HASH_MISSING for e in result.errors)


def test_validator_rejects_ldu_with_empty_bounding_boxes():
    """LDU with empty bounding_boxes → validator rejects with BOUNDING_BOXES_INVALID."""
    ldu = LDU.model_construct(
        id="ldu_1",
        document_id="doc1",
        content_type=LDUContentType.PARAGRAPH,
        text="Hi",
        page_refs=[_page_ref()],
        bounding_boxes=[],
        token_count=1,
        content_hash=compute_content_hash("paragraph", "Hi"),
    )
    result = ChunkValidator().validate([ldu])
    assert result.success is False
    assert any(e.code == BOUNDING_BOXES_INVALID for e in result.errors)


# -----------------------------------------------------------------------------
# validate_or_raise
# -----------------------------------------------------------------------------


def test_validate_or_raise_raises_on_failure():
    """validate_or_raise raises ChunkValidationError with result containing error codes."""
    validator = ChunkValidator()
    broken = _valid_ldu("fig_1", content_type=LDUContentType.FIGURE, text="", raw_payload={})
    with pytest.raises(ChunkValidationError) as exc_info:
        validator.validate_or_raise([broken])
    assert exc_info.value.result.success is False
    assert any(e.code == FIGURE_CAPTION_NOT_UNIFIED for e in exc_info.value.result.errors)
    assert "figure" in str(exc_info.value).lower() or "caption" in str(exc_info.value).lower()


def test_validate_or_raise_returns_ldus_on_success():
    """validate_or_raise returns the list when valid; provenance preserved."""
    ldus = [_valid_ldu("ldu_1")]
    result = ChunkValidator().validate_or_raise(ldus)
    assert result == ldus
    assert result[0].page_refs and result[0].bounding_boxes
