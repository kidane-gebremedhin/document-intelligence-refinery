# BaseExtractor interface and ExtractionResult. Plan §2; spec 03.

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from src.models import DocumentProfile, ExtractedDocument


# -----------------------------------------------------------------------------
# ExtractionResult — unified result wrapper for all strategies
# -----------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Result of a single extractor run. Success when extracted_document is set; else escalation/failure."""

    extracted_document: ExtractedDocument | None = Field(
        default=None,
        description="Set on success; None when escalation or error.",
    )
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    cost_estimate_usd: float = Field(..., ge=0.0, description="0 for non-LLM strategies.")
    token_usage_prompt: int | None = Field(default=None, description="For LLM strategies (e.g. vision).")
    token_usage_completion: int | None = Field(default=None, description="For LLM strategies (e.g. vision).")
    strategy_name: str = Field(
        ...,
        pattern="^(fast_text|layout|vision)$",
        description="Name of the strategy that produced this result.",
    )
    notes: str | None = Field(
        default=None,
        description="E.g. 'confidence_below_threshold', 'error', or escalation reason.",
    )

    @property
    def success(self) -> bool:
        """True if this result contains an ExtractedDocument (router may still reject if confidence < threshold)."""
        return self.extracted_document is not None

    model_config = {"frozen": False}


# -----------------------------------------------------------------------------
# BaseExtractor — protocol for extraction strategies
# -----------------------------------------------------------------------------


@runtime_checkable
class BaseExtractor(Protocol):
    """Interface for extraction strategies. Router calls extract(doc_path, profile) uniformly."""

    def extract(
        self,
        doc_path: Path | str,
        profile: DocumentProfile,
    ) -> ExtractionResult:
        """Run extraction. Returns result with document + confidence on success, or escalation/failure (no document)."""
        ...
