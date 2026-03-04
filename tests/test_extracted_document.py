# Unit tests for ExtractedDocument and subtypes (spec 07 §4). Task: P2-T001.

import pytest
from pydantic import ValidationError

from src.models import (
    BoundingBox,
    ExtractedDocument,
    Figure,
    ReadingOrderEntry,
    RefType,
    Table,
    TableCell,
    TableHeader,
    TableRow,
    TextBlock,
)


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)


# -----------------------------------------------------------------------------
# Bbox / page invariants — element-level
# -----------------------------------------------------------------------------


def test_text_block_valid():
    """TextBlock accepts valid page_number and bbox."""
    b = TextBlock(
        id="b1",
        document_id="doc1",
        page_number=1,
        bbox=_bbox(),
        text="Hello",
        reading_order_index=0,
    )
    assert b.page_number == 1 and b.bbox.x1 == 100.0


def test_text_block_rejects_page_zero():
    """TextBlock page_number must be >= 1."""
    with pytest.raises(ValidationError):
        TextBlock(
            id="b1",
            document_id="doc1",
            page_number=0,
            bbox=_bbox(),
            text="",
            reading_order_index=0,
        )


def test_table_rejects_page_zero():
    """Table page_number must be >= 1."""
    with pytest.raises(ValidationError):
        Table(
            id="t1",
            document_id="doc1",
            page_number=0,
            bbox=_bbox(),
        )


def test_figure_rejects_page_zero():
    """Figure page_number must be >= 1."""
    with pytest.raises(ValidationError):
        Figure(
            id="f1",
            document_id="doc1",
            page_number=0,
            bbox=_bbox(),
        )


# -----------------------------------------------------------------------------
# ExtractedDocument — page range and reading_order refs
# -----------------------------------------------------------------------------


def test_extracted_document_valid_minimal():
    """ExtractedDocument accepts minimal valid payload."""
    doc = ExtractedDocument(
        document_id="doc1",
        pages=3,
        strategy_used="fast_text",
        strategy_confidence=0.9,
    )
    assert doc.pages == 3 and doc.text_blocks == []


def test_extracted_document_rejects_text_block_page_out_of_range():
    """ExtractedDocument rejects text_block with page_number > pages."""
    with pytest.raises(ValidationError) as exc_info:
        ExtractedDocument(
            document_id="doc1",
            pages=2,
            strategy_used="fast_text",
            strategy_confidence=0.9,
            text_blocks=[
                TextBlock(
                    id="b1",
                    document_id="doc1",
                    page_number=3,
                    bbox=_bbox(),
                    text="",
                    reading_order_index=0,
                )
            ],
        )
    assert "page_number" in str(exc_info.value) or "not in" in str(exc_info.value)


def test_extracted_document_rejects_table_page_out_of_range():
    """ExtractedDocument rejects table with page_number > pages."""
    with pytest.raises(ValidationError):
        ExtractedDocument(
            document_id="doc1",
            pages=1,
            strategy_used="layout",
            strategy_confidence=0.8,
            tables=[
                Table(
                    id="t1",
                    document_id="doc1",
                    page_number=2,
                    bbox=_bbox(),
                )
            ],
        )


def test_extracted_document_rejects_reading_order_unknown_ref_id():
    """reading_order ref_id must exist in text_blocks, tables, or figures."""
    with pytest.raises(ValidationError) as exc_info:
        ExtractedDocument(
            document_id="doc1",
            pages=1,
            strategy_used="fast_text",
            strategy_confidence=0.9,
            text_blocks=[
                TextBlock(
                    id="b1",
                    document_id="doc1",
                    page_number=1,
                    bbox=_bbox(),
                    text="",
                    reading_order_index=0,
                )
            ],
            reading_order=[
                ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id="nonexistent", order=0)
            ],
        )
    assert "ref_id" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_extracted_document_accepts_reading_order_matching_ids():
    """reading_order ref_ids that exist in blocks/tables/figures are accepted."""
    doc = ExtractedDocument(
        document_id="doc1",
        pages=1,
        strategy_used="fast_text",
        strategy_confidence=0.9,
        text_blocks=[
            TextBlock(
                id="b1",
                document_id="doc1",
                page_number=1,
                bbox=_bbox(),
                text="",
                reading_order_index=0,
            )
        ],
        reading_order=[
            ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id="b1", order=0)
        ],
    )
    assert len(doc.reading_order) == 1 and doc.reading_order[0].ref_id == "b1"


# -----------------------------------------------------------------------------
# Table structure — header, body_rows, column consistency
# -----------------------------------------------------------------------------


def test_table_valid_no_header():
    """Table with only body_rows (no header) is valid."""
    row = TableRow(
        index=0,
        cells=[
            TableCell(row_index=0, col_index=0, text="A"),
            TableCell(row_index=0, col_index=1, text="B"),
        ],
    )
    t = Table(
        id="t1",
        document_id="doc1",
        page_number=1,
        bbox=_bbox(),
        body_rows=[row],
    )
    assert len(t.body_rows) == 1 and len(t.body_rows[0].cells) == 2


def test_table_valid_header_and_body_same_column_count():
    """Table with header and body having same logical column count is valid."""
    header_row = TableRow(
        index=0,
        cells=[
            TableCell(row_index=0, col_index=0, text="H1"),
            TableCell(row_index=0, col_index=1, text="H2"),
        ],
    )
    body_row = TableRow(
        index=1,
        cells=[
            TableCell(row_index=1, col_index=0, text="a"),
            TableCell(row_index=1, col_index=1, text="b"),
        ],
    )
    t = Table(
        id="t1",
        document_id="doc1",
        page_number=1,
        bbox=_bbox(),
        header=TableHeader(rows=[header_row]),
        body_rows=[body_row],
    )
    assert t.header and len(t.header.rows) == 1
    assert len(t.body_rows) == 1
    assert sum(c.colspan for c in t.header.rows[0].cells) == sum(c.colspan for c in t.body_rows[0].cells)


def test_table_rejects_inconsistent_column_count():
    """Table rejects header/body rows with different logical column count (colspans)."""
    header_row = TableRow(
        index=0,
        cells=[
            TableCell(row_index=0, col_index=0, text="H1"),
            TableCell(row_index=0, col_index=1, text="H2"),
        ],
    )
    # Body row has effective column count 1 (one cell, colspan=1); header has 2.
    body_row = TableRow(
        index=1,
        cells=[
            TableCell(row_index=1, col_index=0, text="a"),
        ],
    )
    with pytest.raises(ValidationError) as exc_info:
        Table(
            id="t1",
            document_id="doc1",
            page_number=1,
            bbox=_bbox(),
            header=TableHeader(rows=[header_row]),
            body_rows=[body_row],
        )
    assert "column" in str(exc_info.value).lower() or "colspan" in str(exc_info.value).lower() or "inconsistent" in str(exc_info.value).lower()


def test_table_rejects_body_rows_different_column_counts():
    """Table rejects body rows with different effective column counts."""
    r1 = TableRow(index=0, cells=[TableCell(row_index=0, col_index=0, text="A"), TableCell(row_index=0, col_index=1, text="B")])
    r2 = TableRow(index=1, cells=[TableCell(row_index=1, col_index=0, text="X")])
    with pytest.raises(ValidationError):
        Table(
            id="t1",
            document_id="doc1",
            page_number=1,
            bbox=_bbox(),
            body_rows=[r1, r2],
        )


# -----------------------------------------------------------------------------
# JSON serializability
# -----------------------------------------------------------------------------


def test_extracted_document_roundtrip_json():
    """ExtractedDocument is JSON-serializable and roundtrips."""
    doc = ExtractedDocument(
        document_id="doc1",
        pages=1,
        strategy_used="fast_text",
        strategy_confidence=0.95,
        text_blocks=[
            TextBlock(
                id="b1",
                document_id="doc1",
                page_number=1,
                bbox=_bbox(),
                text="Hello",
                reading_order_index=0,
            )
        ],
    )
    data = doc.model_dump(mode="json")
    doc2 = ExtractedDocument.model_validate(data)
    assert doc2.document_id == doc.document_id
    assert len(doc2.text_blocks) == 1
    assert doc2.text_blocks[0].text == "Hello"
