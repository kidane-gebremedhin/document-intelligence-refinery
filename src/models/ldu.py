# LDU — Logical Document Unit. Spec 07 §5; spec 04.

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import BoundingBox, PageRef


# -----------------------------------------------------------------------------
# LDUContentType — spec 07 §5.1
# -----------------------------------------------------------------------------


class LDUContentType(str, Enum):
    PARAGRAPH = "paragraph"
    SECTION_INTRO = "section_intro"
    TABLE = "table"
    TABLE_SECTION = "table_section"
    FIGURE = "figure"
    LIST = "list"
    FOOTNOTE = "footnote"
    OTHER = "other"


# -----------------------------------------------------------------------------
# content_hash — canonical content + stable identifiers (spec 04 §7; plan §2.2)
# -----------------------------------------------------------------------------


def canonicalize_text(text: str) -> str:
    """Trim and collapse runs of whitespace to a single space. Layout-stable."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def canonicalize_raw_payload(payload: dict[str, Any]) -> str:
    """Canonical JSON (sorted keys) for tables/figures so key order does not change hash."""
    if not payload:
        return ""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def compute_content_hash(
    content_type: str,
    text: str,
    raw_payload: dict[str, Any] | None = None,
) -> str:
    """
    Deterministic, content-scoped hash. Same canonical content → same hash.
    Does not include page_refs or bounding_boxes (stable under re-pagination).
    Uses SHA-256 truncated to 16 hex chars (64-bit) per spec.
    """
    canonical_text = canonicalize_text(text or "")
    parts = [content_type, canonical_text]
    if raw_payload:
        parts.append(canonicalize_raw_payload(raw_payload))
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# -----------------------------------------------------------------------------
# LDU — spec 07 §5.2
# -----------------------------------------------------------------------------


class LDU(BaseModel):
    """Logical Document Unit: RAG-ready semantic chunk with page_refs and bounding_boxes."""

    id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    content_type: LDUContentType = Field(...)
    text: str = Field(default="", description="Main textual payload.")
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    page_refs: list[PageRef] = Field(..., min_length=1, description="At least one page.")
    bounding_boxes: list[BoundingBox] = Field(..., min_length=1, description="At least one bbox.")
    parent_section_id: str | None = None
    token_count: int = Field(..., ge=0)
    content_hash: str = Field(..., min_length=1)
    relationships: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def page_refs_and_bboxes_non_empty(self) -> "LDU":
        if not self.page_refs:
            raise ValueError("page_refs must be non-empty")
        if not self.bounding_boxes:
            raise ValueError("bounding_boxes must be non-empty")
        if not self.content_hash:
            raise ValueError("content_hash must be non-empty")
        return self

    model_config = {"frozen": False}


__all__ = [
    "LDU",
    "LDUContentType",
    "canonicalize_text",
    "canonicalize_raw_payload",
    "compute_content_hash",
]
