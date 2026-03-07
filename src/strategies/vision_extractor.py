# VisionExtractor — Strategy C: page images → VLM → ExtractedDocument. Spec 03 §6.
# Provider and API key can be set via .env (REFINERY_VISION_*) so no code change is needed.

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

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
from src.strategies.config import load_vision_config

logger = logging.getLogger(__name__)

# Env var names for .env-driven config (no code change). Spec 03 §6.4.
ENV_VISION_PROVIDER = "REFINERY_VISION_PROVIDER"
ENV_VISION_API_KEY = "REFINERY_VISION_API_KEY"
ENV_VISION_API_KEY_ENV = "REFINERY_VISION_API_KEY_ENV"


def _load_dotenv() -> None:
    """Load .env from current working directory or project root into os.environ (minimal parser, no dependency)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent):
        env_file = base / ".env"
        if not env_file.is_file():
            continue
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
        except OSError:
            pass
        break


# Optional: pymupdf for rendering PDF pages to images
try:
    import fitz  # pymupdf
except ImportError:
    fitz = None  # type: ignore[assignment]

# Optional: OpenAI for vision API
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[misc, assignment]

# Optional: Google Gemini for vision API
try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore[assignment]


def _render_pdf_pages(doc_path: Path, max_pages: int, dpi: int = 150) -> list[tuple[int, bytes]]:
    """Render PDF pages to PNG bytes. Returns list of (page_number_1based, png_bytes)."""
    if fitz is None:
        return []
    doc = fitz.open(doc_path)
    try:
        out: list[tuple[int, bytes]] = []
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png_bytes = pix.tobytes("png")
            out.append((i + 1, png_bytes))
        return out
    finally:
        doc.close()


VISION_PROMPT = """Extract structured content from this document page image. Return a JSON object with exactly these keys:
- "text_blocks": list of { "id": string, "text": string, "page": int (1-based), "bbox": { "x0", "y0", "x1", "y1" } }
- "tables": list of { "id": string, "page": int, "bbox": {...}, "headers": list of str, "rows": list of list of str, "caption": optional str }
- "figures": list of { "id": string, "page": int, "bbox": {...}, "caption": optional str }
Use PDF-style coordinates (points). Page must be the 1-based page number provided. Domain hint: """


def _parse_vision_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from model response (may be wrapped in markdown code block)."""
    if "```" in text:
        start = text.find("```")
        if "json" in text[start : start + 10]:
            start = text.find("\n", start) + 1
        end = text.find("```", start)
        text = text[start:end] if end > start else text[start:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def _call_vision_api_openai(
    images: list[tuple[int, bytes]],
    domain_hint: str,
    model: str,
    api_key: str,
) -> dict[str, Any] | None:
    """Call OpenAI vision API. Returns parsed JSON or None."""
    if OpenAI is None or not api_key:
        return None
    client = OpenAI(api_key=api_key)
    prompt = VISION_PROMPT + (domain_hint or "general")
    content: list[Any] = [{"type": "text", "text": prompt}]
    for page_num, png_bytes in images:
        b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"},
        })
        content.append({"type": "text", "text": f"[Page {page_num}]"})
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
        )
        text = resp.choices[0].message.content if resp.choices else ""
        return _parse_vision_json(text)
    except Exception as e:
        logger.warning("OpenAI vision API call failed: %s", e)
        return None


def _call_vision_api_gemini(
    images: list[tuple[int, bytes]],
    domain_hint: str,
    model: str,
    api_key: str,
) -> dict[str, Any] | None:
    """Call Google Gemini vision API. Returns parsed JSON or None."""
    if genai is None or not api_key:
        return None
    genai.configure(api_key=api_key)
    prompt = VISION_PROMPT + (domain_hint or "general")
    parts: list[Any] = [prompt]
    for page_num, png_bytes in images:
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": png_bytes,
            }
        })
        parts.append(f"[Page {page_num}]")
    try:
        gemini_model = genai.GenerativeModel(model)
        response = gemini_model.generate_content(
            parts,
            generation_config={"max_output_tokens": 4096},
        )
        if not response or not response.text:
            logger.warning("Gemini returned empty response")
            return None
        return _parse_vision_json(response.text)
    except Exception as e:
        logger.warning("Gemini vision API call failed: %s", e)
        return None


def _call_vision_api(
    images: list[tuple[int, bytes]],
    document_id: str,
    domain_hint: str,
    provider: str,
    model: str,
    api_key: str,
) -> dict[str, Any] | None:
    """
    Call vision API by provider. provider is 'openai' or 'google'.
    Returns parsed JSON dict with text_blocks, tables, figures, or None on failure.
    """
    if provider and provider.lower() == "google":
        return _call_vision_api_gemini(images, domain_hint, model, api_key)
    return _call_vision_api_openai(images, domain_hint, model, api_key)


def _normalize_vision_response(
    data: dict[str, Any],
    document_id: str,
    num_pages: int,
    source_path: str,
) -> ExtractedDocument | None:
    """Build ExtractedDocument from VLM response. Returns None if invalid."""
    try:
        text_blocks: list[TextBlock] = []
        tables: list[Table] = []
        figures: list[Figure] = []
        reading_order: list[ReadingOrderEntry] = []
        order = 0

        for b in data.get("text_blocks") or []:
            bid = b.get("id") or f"block_{b.get('page', 1)}_{len(text_blocks)}"
            page = int(b.get("page", 1))
            bbox_dict = b.get("bbox") or {}
            bbox = BoundingBox(
                x0=float(bbox_dict.get("x0", 0)),
                y0=float(bbox_dict.get("y0", 0)),
                x1=float(bbox_dict.get("x1", 100)),
                y1=float(bbox_dict.get("y1", 20)),
            )
            text_blocks.append(
                TextBlock(
                    id=bid,
                    document_id=document_id,
                    page_number=page,
                    bbox=bbox,
                    text=(b.get("text") or "").strip(),
                    reading_order_index=order,
                )
            )
            reading_order.append(ReadingOrderEntry(ref_type=RefType.TEXT_BLOCK, ref_id=bid, order=order))
            order += 1

        for t in data.get("tables") or []:
            tid = t.get("id") or f"table_{t.get('page', 1)}_{len(tables)}"
            page = int(t.get("page", 1))
            bbox_dict = t.get("bbox") or {}
            bbox = BoundingBox(
                x0=float(bbox_dict.get("x0", 0)),
                y0=float(bbox_dict.get("y0", 0)),
                x1=float(bbox_dict.get("x1", 100)),
                y1=float(bbox_dict.get("y1", 50)),
            )
            headers = t.get("headers") or []
            rows = t.get("rows") or []
            n_cols = max(len(headers), *(len(r) for r in rows), 1)
            header_cells = [TableCell(row_index=0, col_index=j, text=headers[j] if j < len(headers) else "") for j in range(n_cols)]
            header_row = TableRow(index=0, cells=header_cells)
            body_rows = [
                TableRow(index=i + 1, cells=[TableCell(row_index=i + 1, col_index=j, text=(row[j] if j < len(row) else "")) for j in range(n_cols)])
                for i, row in enumerate(rows)
            ]
            tables.append(
                Table(
                    id=tid,
                    document_id=document_id,
                    page_number=page,
                    bbox=bbox,
                    header=TableHeader(rows=[header_row]),
                    body_rows=body_rows,
                    caption=(t.get("caption") or "").strip() or None,
                )
            )
            reading_order.append(ReadingOrderEntry(ref_type=RefType.TABLE, ref_id=tid, order=order))
            order += 1

        for f in data.get("figures") or []:
            fid = f.get("id") or f"figure_{f.get('page', 1)}_{len(figures)}"
            page = int(f.get("page", 1))
            bbox_dict = f.get("bbox") or {}
            bbox = BoundingBox(
                x0=float(bbox_dict.get("x0", 0)),
                y0=float(bbox_dict.get("y0", 0)),
                x1=float(bbox_dict.get("x1", 100)),
                y1=float(bbox_dict.get("y1", 80)),
            )
            figures.append(
                Figure(
                    id=fid,
                    document_id=document_id,
                    page_number=page,
                    bbox=bbox,
                    caption=(f.get("caption") or "").strip() or None,
                )
            )
            reading_order.append(ReadingOrderEntry(ref_type=RefType.FIGURE, ref_id=fid, order=order))
            order += 1

        return ExtractedDocument(
            document_id=document_id,
            source_path=source_path,
            pages=num_pages,
            text_blocks=text_blocks,
            tables=tables,
            figures=figures,
            reading_order=reading_order,
            metadata={"strategy": "vision"},
            strategy_used="vision",
            strategy_confidence=0.8,
        )
    except Exception as e:
        logger.warning("Failed to normalize vision response: %s", e)
        return None


class VisionExtractor:
    """
    Strategy C: render PDF pages to images, call VLM (e.g. OpenAI vision), normalize to ExtractedDocument.
    Requires pymupdf and openai when used; otherwise returns stub/escalation result.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path
        self._config: dict[str, Any] | None = None

    def _get_config(self) -> dict[str, Any]:
        if self._config is None:
            self._config = load_vision_config(self._config_path)
        return self._config

    def extract(
        self,
        doc_path: Path | str,
        profile: DocumentProfile,
    ) -> ExtractionResult:
        doc_path = Path(doc_path)
        config = self._get_config()
        confidence = float(config.get("confidence_default", 0.8))
        model = config.get("model", "gpt-4o-mini")
        max_pages = int(config.get("max_pages_per_document", 50))

        if fitz is None:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="vision",
                notes="vision requires pymupdf for page rendering",
            )
        _load_dotenv()
        # Provider and API key: .env overrides config (no code change needed). Spec 03 §6.4.
        provider = (os.environ.get(ENV_VISION_PROVIDER) or config.get("provider") or "openai").strip().lower()
        api_key_env_name = (
            os.environ.get(ENV_VISION_API_KEY_ENV)
            or config.get("api_key_env")
            or ("OPENAI_API_KEY" if provider == "openai" else "GOOGLE_API_KEY")
        )
        api_key = (os.environ.get(ENV_VISION_API_KEY) or os.environ.get(api_key_env_name, "")).strip()
        if not api_key:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="vision",
                notes="vision_api_not_configured",
            )
        if provider == "google" and genai is None:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="vision",
                notes="vision provider=google requires: uv add google-generativeai and REFINERY_VISION_API_KEY (or GEMINI_API_KEY) in .env",
            )
        if provider != "google" and OpenAI is None:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="vision",
                notes="vision provider=openai requires: uv add openai and REFINERY_VISION_API_KEY (or REFINERY_VISION_API_KEY_ENV) in .env",
            )

        try:
            images = _render_pdf_pages(doc_path, max_pages)
            if not images:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="vision",
                    notes="no_pages_rendered",
                )
            num_pages = max(p[0] for p in images)
            domain_hint = getattr(profile.domain_hint, "value", str(profile.domain_hint))
            data = _call_vision_api(images, profile.document_id, domain_hint, provider, model, api_key)
            if data is None:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="vision",
                    notes="vision_api_call_failed",
                )
            doc = _normalize_vision_response(
                data,
                profile.document_id,
                num_pages,
                str(doc_path.resolve()),
            )
            if doc is None:
                return ExtractionResult(
                    extracted_document=None,
                    confidence_score=0.0,
                    cost_estimate_usd=0.0,
                    strategy_name="vision",
                    notes="vision_response_invalid",
                )
            return ExtractionResult(
                extracted_document=doc,
                confidence_score=confidence,
                cost_estimate_usd=0.0,  # Caller can track via record_usage
                strategy_name="vision",
                notes=None,
            )
        except Exception as e:
            logger.exception("VisionExtractor failed for %s", doc_path)
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="vision",
                notes=f"error: {e!s}",
            )
