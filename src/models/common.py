# Shared value objects used across Document Intelligence Refinery models.
# Spec: specs/07-models-schemas-spec.md §2 (Shared Value Objects).

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, field_validator


# -----------------------------------------------------------------------------
# BoundingBox — rectangular region on a PDF page (spec §2.1)
# -----------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """Rectangular region on a PDF page. Coordinates in PDF points; origin bottom-left."""

    x0: float = Field(..., description="Left coordinate")
    y0: float = Field(..., description="Bottom coordinate")
    x1: float = Field(..., description="Right coordinate")
    y1: float = Field(..., description="Top coordinate")

    @field_validator("x1")
    @classmethod
    def x1_gt_x0(cls, v: float, info) -> float:
        if "x0" in info.data and v <= info.data["x0"]:
            raise ValueError("x1 must be greater than x0")
        return v

    @field_validator("y1")
    @classmethod
    def y1_gt_y0(cls, v: float, info) -> float:
        if "y0" in info.data and v <= info.data["y0"]:
            raise ValueError("y1 must be greater than y0")
        return v

    model_config = {"frozen": True}


# -----------------------------------------------------------------------------
# PageRef — single page reference (spec §2.2)
# -----------------------------------------------------------------------------


class PageRef(BaseModel):
    """Reference to a single page in a document. Page numbers are 1-based."""

    document_id: str = Field(..., min_length=1)
    page_number: int = Field(..., ge=1, description="1-based page index")

    model_config = {"frozen": True}


# -----------------------------------------------------------------------------
# PageSpan — inclusive page range (spec §2.3)
# -----------------------------------------------------------------------------


class PageSpan(BaseModel):
    """Inclusive range of pages within a document."""

    document_id: str = Field(..., min_length=1)
    page_start: int = Field(..., ge=1, description="First page (1-based)")
    page_end: int = Field(..., ge=1, description="Last page (1-based, inclusive)")

    @field_validator("page_end")
    @classmethod
    def page_end_ge_page_start(cls, v: int, info) -> int:
        if "page_start" in info.data and v < info.data["page_start"]:
            raise ValueError("page_end must be >= page_start")
        return v

    model_config = {"frozen": True}


# -----------------------------------------------------------------------------
# LanguageCode — BCP-47 / ISO-like, 2–5 chars lowercase (spec §2.4)
# -----------------------------------------------------------------------------


def _validate_language_code(v: str) -> str:
    if not isinstance(v, str):
        raise ValueError("LanguageCode must be a string")
    v = v.strip().lower()
    if len(v) < 2 or len(v) > 5:
        raise ValueError("LanguageCode must be 2–5 characters")
    if not v.isascii() or not v.isalpha():
        raise ValueError("LanguageCode must be lowercase letters (BCP-47 style)")
    return v


LanguageCode = Annotated[
    str,
    BeforeValidator(_validate_language_code),
    Field(min_length=2, max_length=5),
]


# -----------------------------------------------------------------------------
# DocumentClass — extraction cost / routing class (spec §3 estimated_extraction_cost)
# -----------------------------------------------------------------------------


class DocumentClass(str, Enum):
    """Document class for extraction routing. Maps to estimated_extraction_cost in DocumentProfile."""

    FAST_TEXT_SUFFICIENT = "fast_text_sufficient"
    NEEDS_LAYOUT_MODEL = "needs_layout_model"
    NEEDS_VISION_MODEL = "needs_vision_model"
