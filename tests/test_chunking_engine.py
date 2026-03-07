# Unit tests for ChunkingEngine (Stage 3). Spec 04 §5–6.

from __future__ import annotations

from src.chunking import ChunkingEngine
from src.models import (
    BoundingBox,
    ExtractedDocument,
    Figure,
    LDUContentType,
    ReadingOrderEntry,
    RefType,
    Table,
    TableCell,
    TableHeader,
    TableRow,
    TextBlock,
)


def _bbox(x0: float = 0, y0: float = 0, x1: float = 100, y1: float = 20) -> BoundingBox:
    return BoundingBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1))


def test_chunking_engine_emits_valid_ldus_with_parent_section_and_list_grouping() -> None:
    doc_id = "doc_test"
    blocks = [
        TextBlock(
            id="b1",
            document_id=doc_id,
            page_number=1,
            bbox=_bbox(0, 700, 500, 740),
            text="1. RISK FACTORS",
            reading_order_index=0,
        ),
        TextBlock(
            id="b2",
            document_id=doc_id,
            page_number=1,
            bbox=_bbox(0, 650, 500, 690),
            text="1) Market volatility",
            reading_order_index=1,
        ),
        TextBlock(
            id="b3",
            document_id=doc_id,
            page_number=1,
            bbox=_bbox(0, 620, 500, 645),
            text="2) Regulatory changes",
            reading_order_index=2,
        ),
        TextBlock(
            id="b4",
            document_id=doc_id,
            page_number=1,
            bbox=_bbox(0, 580, 500, 610),
            text="See Table 1 for details.",
            reading_order_index=3,
        ),
    ]

    table = Table(
        id="t1",
        document_id=doc_id,
        page_number=1,
        bbox=_bbox(0, 400, 500, 560),
        header=TableHeader(
            rows=[
                TableRow(
                    index=0,
                    cells=[
                        TableCell(row_index=0, col_index=0, text="Metric"),
                        TableCell(row_index=0, col_index=1, text="Value"),
                    ],
                )
            ]
        ),
        body_rows=[
            TableRow(
                index=1,
                cells=[
                    TableCell(row_index=1, col_index=0, text="Revenue"),
                    TableCell(row_index=1, col_index=1, text="4.2B"),
                ],
            )
        ],
    )

    fig = Figure(
        id="f1",
        document_id=doc_id,
        page_number=1,
        bbox=_bbox(520, 400, 780, 560),
        caption="Figure 1: Revenue by region",
        type="chart",
    )

    reading = [
        ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id="b1", order=0),
        ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id="b2", order=1),
        ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id="b3", order=2),
        ReadingOrderEntry(ref_type=RefType.TABLE, ref_id="t1", order=3),
        ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id="b4", order=4),
        ReadingOrderEntry(ref_type=RefType.FIGURE, ref_id="f1", order=5),
    ]

    doc = ExtractedDocument(
        document_id=doc_id,
        source_path=None,
        pages=1,
        text_blocks=blocks,
        tables=[table],
        figures=[fig],
        reading_order=reading,
        metadata={},
        strategy_used="layout",
        strategy_confidence=0.9,
    )

    engine = ChunkingEngine()
    ldus = engine.chunk(doc)

    assert len(ldus) >= 4
    header = ldus[0]
    assert header.content_type == LDUContentType.HEADING

    # After the header, each LDU should carry parent_section_id (validator rule R4).
    for ldu in ldus[1:]:
        assert ldu.parent_section_id == header.id
        assert ldu.page_refs and ldu.bounding_boxes and ldu.content_hash

    # List items are grouped into a single LIST LDU
    list_ldus = [l for l in ldus if l.content_type == LDUContentType.LIST]
    assert len(list_ldus) == 1
    assert "Market volatility" in (list_ldus[0].text or "")
    assert "Regulatory changes" in (list_ldus[0].text or "")

    # Table emitted as TABLE with header and rows in raw_payload
    table_ldus = [l for l in ldus if l.content_type == LDUContentType.TABLE]
    assert len(table_ldus) == 1
    assert "header" in table_ldus[0].raw_payload
    assert "rows" in table_ldus[0].raw_payload

    # Cross-reference best-effort: paragraph after the table should link to it
    para = [l for l in ldus if l.content_type == LDUContentType.PARAGRAPH][0]
    assert "references_table" in para.relationships
    assert table_ldus[0].id in para.relationships["references_table"]

    # Figure emitted as FIGURE when caption exists
    fig_ldus = [l for l in ldus if l.content_type == LDUContentType.FIGURE]
    assert len(fig_ldus) == 1
    assert "caption" in fig_ldus[0].raw_payload or "Revenue by region" in (fig_ldus[0].text or "")

