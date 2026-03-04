# LayoutExtractor — Strategy B: layout-aware extraction (tables, figures, reading order). Spec 03 §5.
# backend: mineru or docling only (no pdfplumber).

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None  # type: ignore[misc, assignment]

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
        # DoclingDocument has .texts, .tables, .pictures; use export_to_dict or iterate
        data = doc.export_to_dict() if hasattr(doc, "export_to_dict") else {}
        texts = data.get("texts", []) or getattr(doc, "texts", [])
        tables_data = data.get("tables", []) or getattr(doc, "tables", [])
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
            # Docling may use top-left coords; our BoundingBox is bottom-left. Assume page height 842 for now.
            page_height = 842.0
            bbox = BoundingBox(x0=x0, y0=page_height - y1, x1=x1, y1=page_height - y0)
            text_blocks.append(
                TextBlock(id=bid, document_id=document_id, page_number=page_no, bbox=bbox, text=text, reading_order_index=order)
            )
            reading_order_entries.append((order, 0, 0, RefType.TEXT_BLOCK, bid))
            order += 1
        for i, tbl in enumerate(tables_data):
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
            page_height = 842.0
            bbox = BoundingBox(x0=x0, y0=page_height - y1, x1=x1, y1=page_height - y0)
            tid = f"table_{page_no}_{i}"
            header = TableHeader(rows=[TableRow(index=0, cells=[TableCell(row_index=0, col_index=0, text="")])])
            tables.append(
                Table(id=tid, document_id=document_id, page_number=page_no, bbox=bbox, header=header, body_rows=[])
            )
            reading_order_entries.append((order, 0, 0, RefType.TABLE, tid))
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
            page_height = 842.0
            bbox = BoundingBox(x0=x0, y0=page_height - y1, x1=x1, y1=page_height - y0)
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
