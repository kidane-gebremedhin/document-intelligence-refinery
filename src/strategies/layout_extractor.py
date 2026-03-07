# LayoutExtractor — Strategy B: layout-aware extraction (tables, figures, reading order). Spec 03 §5.
# backend: mineru or docling only (no pdfplumber).
# Tables: use Docling native table.export_to_dataframe() so LDUs get structured header/rows JSON.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None  # type: ignore[misc, assignment]

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]

# MinerU: optional; use backend "mineru" when installed (pip install mineru).
_mineru_available = False
try:
    from magic_pdf.data.dataset import PymuDocDataset  # noqa: F401
    _mineru_available = True
except ImportError:
    pass

from src.models import (
    BoundingBox,
    DocumentProfile,
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
from src.strategies.base import ExtractionResult
from src.strategies.config import load_layout_config

logger = logging.getLogger(__name__)


# Minimum width/height (points) so BoundingBox always satisfies x1 > x0, y1 > y0
_BBOX_MIN_EXTENT = 1.0


def _bbox_from_topleft(
    x0: float, y0_top: float, x1: float, y1_bottom: float, page_height: float = 842.0
) -> BoundingBox:
    """
    Convert top-left origin coords (y down) to our bottom-left BoundingBox (y up).
    Normalize so x0 < x1 and y0 < y1; enforce minimum extent to satisfy strict validators.
    """
    our_y0 = page_height - float(y1_bottom)
    our_y1 = page_height - float(y0_top)
    if our_y0 > our_y1:
        our_y0, our_y1 = our_y1, our_y0
    if x0 > x1:
        x0, x1 = x1, x0
    # Strict validators require x1 > x0 and y1 > y0; ensure minimum extent
    if x1 <= x0:
        x1 = x0 + _BBOX_MIN_EXTENT
    if our_y1 <= our_y0:
        our_y1 = our_y0 + _BBOX_MIN_EXTENT
    return BoundingBox(x0=float(x0), y0=our_y0, x1=float(x1), y1=our_y1)


def _get_docling_bbox(prov_item: Any, page_height: float = 842.0) -> BoundingBox:
    """Extract (x0, y0_top, x1, y1_bottom) from Docling prov item and return our BoundingBox."""
    bbox_dict: dict[str, float] = {}
    rect = getattr(prov_item, "bbox", None) or getattr(prov_item, "rect", None)
    if rect is not None:
        bbox_dict = {
            "l": getattr(rect, "l", 0),
            "t": getattr(rect, "t", 0),
            "r": getattr(rect, "r", 100),
            "b": getattr(rect, "b", 50),
        }
        # Docling BoundingRectangle uses r_x0, r_y0, r_x1, r_y1
        if hasattr(rect, "r_x0"):
            bbox_dict = {
                "l": getattr(rect, "r_x0", 0),
                "t": getattr(rect, "r_y0", 0),
                "r": getattr(rect, "r_x1", 100),
                "b": getattr(rect, "r_y1", 50),
            }
    elif isinstance(prov_item, dict):
        bbox_dict = prov_item.get("bbox", prov_item.get("rect", {})) or {}
    x0 = float(bbox_dict.get("l", bbox_dict.get("x0", 0)))
    y0 = float(bbox_dict.get("t", bbox_dict.get("y0", 0)))
    x1 = float(bbox_dict.get("r", bbox_dict.get("x1", 100)))
    y1 = float(bbox_dict.get("b", bbox_dict.get("y1", 50)))
    return _bbox_from_topleft(x0, y0, x1, y1, page_height)


def _docling_table_to_our_table(
    docling_table: Any,
    doc: Any,
    document_id: str,
    index: int,
    page_height: float = 842.0,
) -> Table:
    """
    Convert a Docling table object to our Table model with structured header and body_rows.
    Uses table.export_to_dataframe(doc=...) when available so LDUs get real headers and values.
    """
    page_no = 1
    bbox = _bbox_from_topleft(0, 0, 100, 50, page_height)
    prov = getattr(docling_table, "prov", []) or []
    if prov:
        p0 = prov[0]
        page_no = int(getattr(p0, "page_no", getattr(p0, "page", 1)))
        bbox = _get_docling_bbox(p0, page_height)
    tid = f"table_{page_no}_{index}"

    header_cells: list[TableCell] = []
    body_rows: list[TableRow] = []
    if pd is not None and hasattr(docling_table, "export_to_dataframe"):
        try:
            df = docling_table.export_to_dataframe(doc=doc)
            if df is not None and not df.empty:
                cols = list(df.columns)
                header_cells = [
                    TableCell(row_index=0, col_index=j, text=str(cols[j]) if j < len(cols) else "")
                    for j in range(len(cols))
                ]
                for i in range(len(df)):
                    row_vals = df.iloc[i].tolist()
                    cells = [
                        TableCell(
                            row_index=i + 1,
                            col_index=j,
                            text=str(row_vals[j]) if j < len(row_vals) else "",
                        )
                        for j in range(len(cols))
                    ]
                    body_rows.append(TableRow(index=i + 1, cells=cells))
        except Exception as e:
            logger.debug("Docling export_to_dataframe failed for table %s: %s", tid, e)

    if not header_cells:
        header_cells = [TableCell(row_index=0, col_index=0, text="")]
    header = TableHeader(rows=[TableRow(index=0, cells=header_cells)])
    return Table(
        id=tid,
        document_id=document_id,
        page_number=page_no,
        bbox=bbox,
        header=header,
        body_rows=body_rows,
    )


def _extract_layout_docling(
    doc_path: Path,
    document_id: str,
    confidence: float,
) -> ExtractedDocument | None:
    """Extract using Docling and map to ExtractedDocument. Returns None if Docling not installed or conversion fails."""
    if DocumentConverter is None:
        return None
    try:
        converter = DocumentConverter()
        result = converter.convert(doc_path)
        doc = result.document
        if doc is None:
            return None
        # Prefer native doc.tables so we can call export_to_dataframe for structured header/rows
        data = doc.export_to_dict() if hasattr(doc, "export_to_dict") else {}
        texts = data.get("texts", []) or getattr(doc, "texts", [])
        docling_tables = getattr(doc, "tables", []) or data.get("tables", [])
        pictures = data.get("pictures", []) or getattr(doc, "pictures", [])
        text_blocks = []
        tables = []
        figures = []
        reading_order_entries: list[tuple[int, float, float, RefType, str]] = []
        order = 0
        for i, t in enumerate(texts):
            if isinstance(t, dict):
                text = t.get("text", "") or ""
                prov = t.get("prov", [])
                page_no = 1
                bbox_dict = {}
                if prov:
                    p0 = prov[0] if isinstance(prov[0], dict) else {}
                    page_no = int(p0.get("page_no", p0.get("page", 1)))
                    bbox_dict = p0.get("bbox", p0.get("rect", {})) or {}
                else:
                    bbox_dict = t.get("bbox", t.get("rect", {})) or {}
                x0 = float(bbox_dict.get("l", bbox_dict.get("x0", 0)))
                y0 = float(bbox_dict.get("t", bbox_dict.get("y0", 0)))
                x1 = float(bbox_dict.get("r", bbox_dict.get("x1", 100)))
                y1 = float(bbox_dict.get("b", bbox_dict.get("y1", 20)))
            else:
                text = getattr(t, "text", "") or ""
                page_no = getattr(t, "page_no", 1)
                prov = getattr(t, "prov", []) or []
                if prov:
                    p0 = prov[0]
                    rect = getattr(p0, "bbox", None) or getattr(p0, "rect", None)
                    if rect:
                        x0, y0 = getattr(rect, "l", 0), getattr(rect, "t", 0)
                        x1, y1 = getattr(rect, "r", 100), getattr(rect, "b", 20)
                    else:
                        x0, y0, x1, y1 = 0, 0, 100, 20
                else:
                    x0, y0, x1, y1 = 0, 0, 100, 20
            bid = f"block_{page_no}_{i}"
            bbox = _bbox_from_topleft(x0, y0, x1, y1)
            text_blocks.append(
                TextBlock(id=bid, document_id=document_id, page_number=page_no, bbox=bbox, text=text, reading_order_index=order)
            )
            reading_order_entries.append((order, 0, 0, RefType.TEXT_BLOCK, bid))
            order += 1
        for i, tbl in enumerate(docling_tables):
            if hasattr(tbl, "export_to_dataframe"):
                our_table = _docling_table_to_our_table(tbl, doc, document_id, i)
            else:
                if isinstance(tbl, dict):
                    page_no = int(tbl.get("page_no", tbl.get("page", 1)))
                    bbox_dict = tbl.get("bbox", tbl.get("rect", {})) or {}
                else:
                    page_no = getattr(tbl, "page_no", 1)
                    bbox_dict = {}
                x0 = float(bbox_dict.get("l", 0))
                y0 = float(bbox_dict.get("t", 0))
                x1 = float(bbox_dict.get("r", 100))
                y1 = float(bbox_dict.get("b", 50))
                bbox = _bbox_from_topleft(x0, y0, x1, y1)
                tid = f"table_{page_no}_{i}"
                header = TableHeader(rows=[TableRow(index=0, cells=[TableCell(row_index=0, col_index=0, text="")])])
                our_table = Table(id=tid, document_id=document_id, page_number=page_no, bbox=bbox, header=header, body_rows=[])
            tables.append(our_table)
            reading_order_entries.append((order, 0, 0, RefType.TABLE, our_table.id))
            order += 1
        for i, pic in enumerate(pictures):
            if isinstance(pic, dict):
                page_no = int(pic.get("page_no", pic.get("page", 1)))
                bbox_dict = pic.get("bbox", pic.get("rect", {})) or {}
            else:
                page_no = getattr(pic, "page_no", 1)
                bbox_dict = {}
            x0 = float(bbox_dict.get("l", 0))
            y0 = float(bbox_dict.get("t", 0))
            x1 = float(bbox_dict.get("r", 100))
            y1 = float(bbox_dict.get("b", 80))
            bbox = _bbox_from_topleft(x0, y0, x1, y1)
            fid = f"figure_{page_no}_{i}"
            figures.append(Figure(id=fid, document_id=document_id, page_number=page_no, bbox=bbox, caption=None))
            reading_order_entries.append((order, 0, 0, RefType.FIGURE, fid))
            order += 1
        reading_order_entries.sort(key=lambda r: r[0])
        reading_order = [ReadingOrderEntry(ref_type=ref_type, ref_id=ref_id, order=idx) for idx, (_, _, _, ref_type, ref_id) in enumerate(reading_order_entries)]
        num_pages = max([p.page_number for p in text_blocks] + [t.page_number for t in tables] + [f.page_number for f in figures], default=1)
        return ExtractedDocument(
            document_id=document_id,
            source_path=str(doc_path.resolve()),
            pages=num_pages,
            text_blocks=text_blocks,
            tables=tables,
            figures=figures,
            reading_order=reading_order,
            metadata={"backend": "docling"},
            strategy_used="layout",
            strategy_confidence=confidence,
        )
    except Exception as e:
        logger.warning("Docling extraction failed: %s", e)
        return None


def _extract_layout_mineru(
    doc_path: Path,
    document_id: str,
    confidence: float,
) -> ExtractedDocument | None:
    """Extract using MinerU and map to ExtractedDocument. Returns None if MinerU not installed or conversion fails."""
    if not _mineru_available:
        return None
    # MinerU pipeline requires more setup (config, temp dirs, etc.). Return None for now so caller reports "mineru not installed" or "mineru adapter not implemented".
    logger.warning("MinerU adapter not fully implemented; use backend docling")
    return None


class LayoutExtractor:
    """
    Strategy B: extract text blocks, tables (structured), and figures with reading order.
    Backend must be MinerU or Docling only (config: layout.backend).
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path
        self._config: dict[str, Any] | None = None

    def _get_config(self) -> dict[str, Any]:
        if self._config is None:
            self._config = load_layout_config(self._config_path)
        return self._config

    def extract(
        self,
        doc_path: Path | str,
        profile: DocumentProfile,
    ) -> ExtractionResult:
        doc_path = Path(doc_path)
        config = self._get_config()
        confidence = float(config.get("confidence_default", 0.75))
        first_row_as_header = config.get("first_row_as_header", True)
        backend = (config.get("backend") or "docling").strip().lower()

        if backend == "docling":
            if DocumentConverter is None:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="layout",
                    notes="backend docling not installed (pip install docling)",
                )
            doc = _extract_layout_docling(doc_path, profile.document_id, confidence)
            if doc is None:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="layout",
                    notes="docling conversion failed",
                )
            return ExtractionResult(
                extracted_document=doc,
                confidence_score=confidence,
                cost_estimate_usd=0.0,
                strategy_name="layout",
                notes=None,
            )

        if backend == "mineru":
            if not _mineru_available:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="layout",
                    notes="backend mineru not installed (pip install mineru)",
                )
            doc = _extract_layout_mineru(doc_path, profile.document_id, confidence)
            if doc is None:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="layout",
                    notes="mineru adapter not fully implemented; use docling",
                )
            return ExtractionResult(
                extracted_document=doc,
                confidence_score=confidence,
                cost_estimate_usd=0.0,
                strategy_name="layout",
                notes=None,
            )

        return ExtractionResult(
            extracted_document=None,
            confidence_score=0.0,
            cost_estimate_usd=0.0,
            strategy_name="layout",
            notes=f"layout backend must be mineru or docling (got {backend!r}); install one: pip install docling or pip install mineru",
        )
