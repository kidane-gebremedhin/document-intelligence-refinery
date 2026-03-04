# DocumentProfile — output of the Triage Agent; governs extraction strategy selection.
# Spec: specs/07-models-schemas-spec.md §3.

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import LanguageCode


# -----------------------------------------------------------------------------
# Enums (spec §3)
# -----------------------------------------------------------------------------


class OriginType(str, Enum):
    NATIVE_DIGITAL = "native_digital"
    SCANNED_IMAGE = "scanned_image"
    MIXED = "mixed"
    FORM_FILLABLE = "form_fillable"


class LayoutComplexity(str, Enum):
    SINGLE_COLUMN = "single_column"
    MULTI_COLUMN = "multi_column"
    TABLE_HEAVY = "table_heavy"
    FIGURE_HEAVY = "figure_heavy"
    MIXED = "mixed"


class DomainHint(str, Enum):
    FINANCIAL = "financial"
    LEGAL = "legal"
    TECHNICAL = "technical"
    MEDICAL = "medical"
    GENERAL = "general"


class EstimatedExtractionCost(str, Enum):
    FAST_TEXT_SUFFICIENT = "fast_text_sufficient"
    NEEDS_LAYOUT_MODEL = "needs_layout_model"
    NEEDS_VISION_MODEL = "needs_vision_model"


# -----------------------------------------------------------------------------
# DocumentProfile
# -----------------------------------------------------------------------------

class DocumentProfile(BaseModel):
    """
    Output of the Triage Agent. Governs extraction strategy selection.
    Stored at .refinery/profiles/{document_id}.json.
    """

    document_id: str = Field(..., min_length=1, description="Stable ID; key in .refinery/profiles")
    origin_type: OriginType = Field(...)
    layout_complexity: LayoutComplexity = Field(...)
    language: LanguageCode = Field(...)
    language_confidence: float = Field(..., ge=0.0, le=1.0, description="0.0–1.0")
    domain_hint: DomainHint = Field(...)
    estimated_extraction_cost: EstimatedExtractionCost = Field(...)
    triage_confidence_score: float = Field(..., ge=0.0, le=1.0, description="0.0–1.0")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    page_count: int = Field(..., ge=1, description="Number of pages")
    metadata: dict[str, Any] | None = Field(default=None, description="Free-form extra signals")
    notes: str | None = Field(default=None)

    @model_validator(mode="after")
    def triage_rules(self) -> "DocumentProfile":
        """Enforce: (1) scanned_image → needs_vision_model; (2) complex layout → needs_layout or vision; (3) only native_digital + single_column → fast_text_sufficient."""
        origin = self.origin_type
        layout = self.layout_complexity
        cost = self.estimated_extraction_cost

        if origin == OriginType.SCANNED_IMAGE and cost != EstimatedExtractionCost.NEEDS_VISION_MODEL:
            raise ValueError(
                "origin_type=scanned_image requires estimated_extraction_cost=needs_vision_model"
            )

        complex_layouts = (
            LayoutComplexity.TABLE_HEAVY,
            LayoutComplexity.MULTI_COLUMN,
            LayoutComplexity.FIGURE_HEAVY,
            LayoutComplexity.MIXED,
        )
        if layout in complex_layouts and cost == EstimatedExtractionCost.FAST_TEXT_SUFFICIENT:
            raise ValueError(
                f"layout_complexity={layout.value} requires estimated_extraction_cost in "
                "needs_layout_model or needs_vision_model"
            )

        if cost == EstimatedExtractionCost.FAST_TEXT_SUFFICIENT and (
            origin != OriginType.NATIVE_DIGITAL or layout != LayoutComplexity.SINGLE_COLUMN
        ):
            raise ValueError(
                "estimated_extraction_cost=fast_text_sufficient is only allowed when "
                "origin_type=native_digital and layout_complexity=single_column"
            )

        return self

    def to_profile_json(self, *, exclude_none: bool = True, indent: int | None = 2) -> str:
        """Serialize to JSON for .refinery/profiles/{document_id}.json. Deterministic field order."""
        return self.model_dump_json(exclude_none=exclude_none, indent=indent)

    model_config = {
        "frozen": False,
        "str_strip_whitespace": True,
        "use_enum_values": False,
    }


__all__ = [
    "DocumentProfile",
    "OriginType",
    "LayoutComplexity",
    "DomainHint",
    "EstimatedExtractionCost",
]
