# FastTextExtractor — Strategy A: text-stream extraction with confidence. Spec 03 §4; plan §3.1.
# backend: pdfplumber or pymupdf.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pdfplumber

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None  # type: ignore[assignment]

from src.models import (
    BoundingBox,
    DocumentProfile,
    ExtractedDocument,
    ReadingOrderEntry,
    RefType,
    TextBlock,
)
from src.strategies.base import ExtractionResult
from src.strategies.config import load_fast_text_config

logger = logging.getLogger(__name__)


def _plumber_bbox_to_model(x0: float, top: float, x1: float, bottom: float, page_height: float) -> BoundingBox:
    """Convert pdfplumber (top-left origin) to BoundingBox (bottom-left origin, PDF points)."""
    return BoundingBox(
        x0=x0,
        y0=page_height - bottom,
        x1=x1,
        y1=page_height - top,
    )


def _pymupdf_bbox_to_model(x0: float, y0: float, x1: float, y1: float, page_height: float) -> BoundingBox:
    """Convert pymupdf (top-left origin) to BoundingBox (bottom-left origin, PDF points)."""
    return BoundingBox(
        x0=x0,
        y0=page_height - y1,
        x1=x1,
        y1=page_height - y0,
    )


def _compute_confidence_signals(
    pages_data: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Compute confidence in [0, 1] and a signals dict for metadata.
    Uses: char count per page, char density, image area ratio, whitespace ratio, missing-text indicators.
    """
    min_chars = config.get("min_chars_per_page", 50)
    max_img_ratio = config.get("max_image_area_ratio", 0.5)
    min_density = config.get("min_char_density_per_10k_points2", 1.0)

    total_chars = 0
    total_page_area = 0.0
    total_text_area = 0.0
    total_image_area = 0.0
    pages_with_low_chars = 0
    pages_with_font = 0
    num_pages = len(pages_data)

    for p in pages_data:
        total_chars += p["char_count"]
        total_page_area += p["width"] * p["height"]
        total_text_area += p["text_area"]
        total_image_area += p["image_area"]
        if p["char_count"] < min_chars:
            pages_with_low_chars += 1
        if p.get("has_font_metadata", False):
            pages_with_font += 1

    if num_pages == 0 or total_page_area <= 0:
        score = 0.0
        signals = {
            "char_count_total": 0,
            "char_density_per_10k_points2": 0.0,
            "image_area_ratio": 0.0,
            "whitespace_ratio": 1.0,
            "pages_with_low_chars": 0,
            "fraction_pages_with_font": 0.0,
            "missing_text_indicator": True,
        }
        return score, signals

    char_density = (total_chars / (total_page_area / 10_000.0)) if total_page_area else 0.0
    image_area_ratio = total_image_area / total_page_area if total_page_area else 0.0
    text_area_ratio = total_text_area / total_page_area if total_page_area else 0.0
    whitespace_ratio = max(0.0, 1.0 - text_area_ratio - image_area_ratio)
    fraction_low_char_pages = pages_with_low_chars / num_pages
    fraction_pages_with_font = pages_with_font / num_pages
    missing_text_indicator = fraction_low_char_pages > 0.5 or total_chars < min_chars

    # Deterministic score: penalize low chars, low density, high image ratio, high whitespace, missing text
    score = 1.0
    if char_density < min_density:
        score *= max(0.0, char_density / min_density) if min_density else 0.0
    if image_area_ratio > max_img_ratio:
        score *= max(0.0, 1.0 - (image_area_ratio - max_img_ratio) / (1.0 - max_img_ratio))
    if fraction_low_char_pages > 0:
        score *= 1.0 - (fraction_low_char_pages * 0.5)
    if not fraction_pages_with_font and total_chars > 0:
        score *= 0.8
    if missing_text_indicator:
        score *= 0.7
    if whitespace_ratio > 0.8:
        score *= 0.9
    score = max(0.0, min(1.0, score))

    signals = {
        "char_count_total": total_chars,
        "char_density_per_10k_points2": round(char_density, 4),
        "image_area_ratio": round(image_area_ratio, 4),
        "whitespace_ratio": round(whitespace_ratio, 4),
        "pages_with_low_chars": pages_with_low_chars,
        "fraction_pages_with_font": round(fraction_pages_with_font, 4),
        "missing_text_indicator": missing_text_indicator,
    }
    return score, signals


def _extract_with_pymupdf(
    doc_path: Path,
) -> tuple[list[dict[str, Any]], list[tuple[int, float, float, float, float, str]]]:
    """
    Extract text blocks and page stats using pymupdf. Returns (pages_data, all_blocks).
    all_blocks: (page_num_1based, x0, top, x1, bottom, text) with top-left origin.
    """
    if fitz is None:
        raise RuntimeError("pymupdf is not installed")
    doc = fitz.open(doc_path)
    pages_data: list[dict[str, Any]] = []
    all_blocks: list[tuple[int, float, float, float, float, str]] = []
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            pnum = page_num + 1
            rect = page.rect
            width = rect.width
            height = rect.height
            page_area = width * height
            text_dict = page.get_text("dict")
            blocks = text_dict.get("blocks") or []
            char_count = 0
            text_area = 0.0
            for block in blocks:
                bbox = block.get("bbox") or (0, 0, 0, 0)
                x0, y0, x1, y1 = bbox
                line_texts: list[str] = []
                for line in block.get("lines") or []:
                    for span in line.get("spans") or []:
                        t = span.get("text", "")
                        line_texts.append(t)
                        char_count += len(t)
                text = " ".join(line_texts).strip()
                if text:
                    text_area += (x1 - x0) * (y1 - y0)
                    all_blocks.append((pnum, x0, y0, x1, y1, text))
            # Approximate image area: pymupdf get_image_info returns list of images
            image_area = 0.0
            for img in page.get_images():
                try:
                    xref = img[0]
                    bbox_rect = page.get_image_bbox(xref)
                    if bbox_rect:
                        image_area += bbox_rect.width * bbox_rect.height
                except Exception:
                    pass
            pages_data.append({
                "char_count": char_count,
                "width": width,
                "height": height,
                "text_area": text_area,
                "image_area": image_area,
                "has_font_metadata": True,  # pymupdf typically has text layer
            })
    finally:
        doc.close()
    return pages_data, all_blocks


class FastTextExtractor:
    """Strategy A: extract text blocks with bbox and reading order; confidence from char density, image ratio, signals."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path
        self._config: dict[str, Any] | None = None

    def _get_config(self) -> dict[str, Any]:
        if self._config is None:
            self._config = load_fast_text_config(self._config_path)
        return self._config

    def extract(
        self,
        doc_path: Path | str,
        profile: DocumentProfile,
    ) -> ExtractionResult:
        doc_path = Path(doc_path)
        config = self._get_config()
        threshold = config.get("confidence_threshold", 0.5)
        backend = (config.get("backend") or "pdfplumber").strip().lower()

        if backend == "pymupdf":
            return self._extract_pymupdf(doc_path, profile, config, threshold)
        return self._extract_pdfplumber(doc_path, profile, config, threshold)

    def _extract_pymupdf(
        self,
        doc_path: Path,
        profile: DocumentProfile,
        config: dict[str, Any],
        threshold: float,
    ) -> ExtractionResult:
        if fitz is None:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="fast_text",
                notes="backend pymupdf requires pymupdf",
            )
        try:
            pages_data, all_blocks = _extract_with_pymupdf(doc_path)
            confidence_score, signals = _compute_confidence_signals(pages_data, config)
            if confidence_score < threshold:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=confidence_score,
                    cost_estimate_usd=0.0,
                    strategy_name="fast_text",
                    notes="confidence_below_threshold",
                )
            document_id = profile.document_id
            num_pages = len(pages_data)
            text_blocks = []
            reading_order_entries = []
            for idx, (pnum, x0, y0_top, x1, y1_bottom, text) in enumerate(all_blocks):
                page_height = pages_data[pnum - 1]["height"]
                bbox = _pymupdf_bbox_to_model(x0, y0_top, x1, y1_bottom, page_height)
                block_id = f"block_{pnum}_{idx}"
                text_blocks.append(
                    TextBlock(
                        id=block_id,
                        document_id=document_id,
                        page_number=pnum,
                        bbox=bbox,
                        text=text,
                        reading_order_index=idx,
                    )
                )
                reading_order_entries.append(ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id=block_id, order=idx))
            doc = ExtractedDocument(
                document_id=document_id,
                source_path=str(doc_path.resolve()),
                pages=num_pages,
                text_blocks=text_blocks,
                tables=[],
                figures=[],
                reading_order=reading_order_entries,
                metadata={"fast_text_confidence_signals": signals, "backend": "pymupdf"},
                strategy_used="fast_text",
                strategy_confidence=confidence_score,
            )
            return ExtractionResult(
                extracted_document=doc,
                confidence_score=confidence_score,
                cost_estimate_usd=0.0,
                strategy_name="fast_text",
                notes=None,
            )
        except Exception as e:
            logger.exception("FastTextExtractor (pymupdf) failed for %s", doc_path)
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="fast_text",
                notes=f"error: {e!s}",
            )

    def _extract_pdfplumber(
        self,
        doc_path: Path,
        profile: DocumentProfile,
        config: dict[str, Any],
        threshold: float,
    ) -> ExtractionResult:
        try:
            with pdfplumber.open(doc_path) as pdf:
                pages_data: list[dict[str, Any]] = []
                all_blocks: list[tuple[int, float, float, float, float, str]] = []  # page_1based, x0, top, x1, bottom, text

                for page_num, page in enumerate(pdf.pages, start=1):
                    w = page.width
                    h = page.height
                    page_area = w * h

                    # Words for text blocks (bbox + text)
                    words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
                    # Group by line (similar top)
                    line_tolerance = 5
                    lines: list[list[dict]] = []
                    for word in sorted(words, key=lambda x: (x["top"], x["x0"])):
                        x0, top, x1, bottom = word["x0"], word["top"], word["x1"], word["bottom"]
                        text = word.get("text", "")
                        if not lines or abs(lines[-1][0]["top"] - top) > line_tolerance:
                            lines.append([{"x0": x0, "top": top, "x1": x1, "bottom": bottom, "text": text}])
                        else:
                            lines[-1].append({"x0": x0, "top": top, "x1": x1, "bottom": bottom, "text": text})

                    text_area = 0.0
                    char_count = 0
                    for line in lines:
                        if not line:
                            continue
                        x0 = min(w["x0"] for w in line)
                        x1 = max(w["x1"] for w in line)
                        top = min(w["top"] for w in line)
                        bottom = max(w["bottom"] for w in line)
                        text_area += (x1 - x0) * (bottom - top)
                        line_text = " ".join(w["text"] for w in line)
                        char_count += len(line_text)
                        all_blocks.append((page_num, x0, top, x1, bottom, line_text))

                    # Image area
                    imgs = getattr(page, "images", []) or []
                    image_area = sum(
                        (img.get("x1", 0) - img.get("x0", 0)) * (img.get("bottom", 0) - img.get("top", 0))
                        for img in imgs
                    )

                    # Font metadata: do we have chars with font info?
                    chars = page.chars or []
                    has_font = any(c.get("fontname") for c in chars) if chars else False

                    pages_data.append({
                        "char_count": char_count,
                        "width": w,
                        "height": h,
                        "text_area": text_area,
                        "image_area": image_area,
                        "has_font_metadata": has_font,
                    })

                confidence_score, signals = _compute_confidence_signals(pages_data, config)

                if confidence_score < threshold:
                    return ExtractionResult(
                        extracted_document=None,
                        confidence_score=confidence_score,
                        cost_estimate_usd=0.0,
                        strategy_name="fast_text",
                        notes="confidence_below_threshold",
                    )

                # Build ExtractedDocument
                document_id = profile.document_id
                num_pages = len(pdf.pages)
                text_blocks: list[TextBlock] = []
                reading_order_entries: list[ReadingOrderEntry] = []
                for idx, (pnum, x0, top, x1, bottom, text) in enumerate(all_blocks):
                    page = pdf.pages[pnum - 1]
                    page_height = page.height
                    bbox = _plumber_bbox_to_model(x0, top, x1, bottom, page_height)
                    block_id = f"block_{pnum}_{idx}"
                    text_blocks.append(
                        TextBlock(
                            id=block_id,
                            document_id=document_id,
                            page_number=pnum,
                            bbox=bbox,
                            text=text,
                            reading_order_index=idx,
                        )
                    )
                    reading_order_entries.append(
                        ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id=block_id, order=idx)
                    )

                metadata: dict[str, Any] = {
                    "fast_text_confidence_signals": signals,
                }

                doc = ExtractedDocument(
                    document_id=document_id,
                    source_path=str(doc_path.resolve()),
                    pages=num_pages,
                    text_blocks=text_blocks,
                    tables=[],
                    figures=[],
                    reading_order=reading_order_entries,
                    metadata=metadata,
                    strategy_used="fast_text",
                    strategy_confidence=confidence_score,
                )

                return ExtractionResult(
                    extracted_document=doc,
                    confidence_score=confidence_score,
                    cost_estimate_usd=0.0,
                    strategy_name="fast_text",
                    notes=None,
                )

        except Exception as e:
            logger.exception("FastTextExtractor failed for %s", doc_path)
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="fast_text",
                notes=f"error: {e!s}",
            )
