# ExtractedDocument and subtypes — extraction output schema. Spec 07 §4.

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import BoundingBox


# -----------------------------------------------------------------------------
# TextBlock — spec §4.1
# -----------------------------------------------------------------------------


class TextBlock(BaseModel):
    """Contiguous block of text with spatial provenance."""

    id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    page_number: int = Field(..., ge=1)
    bbox: BoundingBox
    text: str = Field(default="")
    reading_order_index: int = Field(..., ge=0)
    style: dict[str, Any] | None = None
    section_hint: str | None = None

    model_config = {"frozen": False}


# -----------------------------------------------------------------------------
# TableCell, TableRow, TableHeader — spec §4.2–4.4
# -----------------------------------------------------------------------------


class TableCell(BaseModel):
    """Single cell in a table row."""

    row_index: int = Field(..., ge=0)
    col_index: int = Field(..., ge=0)
    text: str = Field(default="")
    bbox: BoundingBox | None = None
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)

    model_config = {"frozen": False}


class TableRow(BaseModel):
    """Row of table cells."""

    index: int = Field(..., ge=0)
    cells: list[TableCell] = Field(default_factory=list, min_length=0)

    model_config = {"frozen": False}


class TableHeader(BaseModel):
    """Table header (one or more rows)."""

    rows: list[TableRow] = Field(default_factory=list)
    bbox: BoundingBox | None = None

    model_config = {"frozen": False}


def _effective_column_count(row: TableRow) -> int:
    """Logical column count for a row (sum of colspans)."""
    return sum(c.colspan for c in row.cells)


# -----------------------------------------------------------------------------
# Table — spec §4.5
# -----------------------------------------------------------------------------


class Table(BaseModel):
    """Structured table with header and body rows."""

    id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    page_number: int = Field(..., ge=1)
    bbox: BoundingBox
    title: str | None = None
    caption: str | None = None
    header: TableHeader | None = None
    body_rows: list[TableRow] = Field(default_factory=list)
    source_text_block_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def table_structural_consistency(self) -> "Table":
        """Header + body rows must have same logical column count (considering colspans)."""
        all_rows: list[TableRow] = []
        if self.header and self.header.rows:
            all_rows.extend(self.header.rows)
        all_rows.extend(self.body_rows)
        if not all_rows:
            return self
        counts = [_effective_column_count(r) for r in all_rows]
        if len(set(counts)) > 1:
            raise ValueError(
                f"Table rows have inconsistent column counts (considering colspan): {counts}"
            )
        return self

    model_config = {"frozen": False}


# -----------------------------------------------------------------------------
# Figure — spec §4.6
# -----------------------------------------------------------------------------


class Figure(BaseModel):
    """Figure or image region with provenance."""

    id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    page_number: int = Field(..., ge=1)
    bbox: BoundingBox
    caption: str | None = None
    type: str | None = None  # e.g. "chart", "photo", "diagram"
    alt_text: str | None = None

    model_config = {"frozen": False}


# -----------------------------------------------------------------------------
# ReadingOrderEntry — spec 03 §3.5
# -----------------------------------------------------------------------------


class RefType(str, Enum):
    TEXT_BLOCK = "text_block"
    TABLE = "table"
    FIGURE = "figure"


class ReadingOrderEntry(BaseModel):
    """Reference to an element in reading order."""

    ref_type: RefType
    ref_id: str = Field(..., min_length=1)
    order: int = Field(..., ge=0)

    model_config = {"frozen": True}


# -----------------------------------------------------------------------------
# ExtractedDocument — spec §4.7
# -----------------------------------------------------------------------------


class ExtractedDocument(BaseModel):
    """Top-level container for extraction output. All elements have page + bbox (constitution)."""

    document_id: str = Field(..., min_length=1)
    source_path: str | None = None
    pages: int = Field(..., ge=1)
    text_blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    reading_order: list[ReadingOrderEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    strategy_used: str = Field(..., pattern="^(fast_text|layout|vision)$")
    strategy_confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def page_and_bbox_in_range(self) -> "ExtractedDocument":
        """All page_number in [1, pages]; every element has non-null bbox (constitution)."""
        for i, b in enumerate(self.text_blocks):
            if b.page_number < 1 or b.page_number > self.pages:
                raise ValueError(
                    f"text_blocks[{i}].page_number {b.page_number} not in [1, {self.pages}]"
                )
        for i, t in enumerate(self.tables):
            if t.page_number < 1 or t.page_number > self.pages:
                raise ValueError(
                    f"tables[{i}].page_number {t.page_number} not in [1, {self.pages}]"
                )
        for i, f in enumerate(self.figures):
            if f.page_number < 1 or f.page_number > self.pages:
                raise ValueError(
                    f"figures[{i}].page_number {f.page_number} not in [1, {self.pages}]"
                )
        # reading_order ref_ids must exist in text_blocks, tables, or figures
        valid_ids = {b.id for b in self.text_blocks} | {t.id for t in self.tables} | {fig.id for fig in self.figures}
        for entry in self.reading_order:
            if entry.ref_id not in valid_ids:
                raise ValueError(f"reading_order ref_id {entry.ref_id!r} not found in text_blocks/tables/figures")
        return self

    model_config = {"frozen": False}


__all__ = [
    "TextBlock",
    "TableCell",
    "TableRow",
    "TableHeader",
    "Table",
    "Figure",
    "ReadingOrderEntry",
    "RefType",
    "ExtractedDocument",
]
