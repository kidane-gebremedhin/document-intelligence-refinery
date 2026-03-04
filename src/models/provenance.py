# ProvenanceItem and ProvenanceChain — audit trail for answers. Spec 07 §7.

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .common import BoundingBox


# -----------------------------------------------------------------------------
# ProvenanceItem — spec 07 §7.1
# -----------------------------------------------------------------------------


class ProvenanceItem(BaseModel):
    """Single citation: document, page, bbox, content_hash, snippet. Required for LDU-backed provenance."""

    document_id: str = Field(..., min_length=1)
    document_name: str = Field(..., min_length=1, description="Human-readable (e.g. filename, report title).")
    page_number: int = Field(..., ge=1)
    bbox: BoundingBox = Field(..., description="Spatial location in the document.")
    content_hash: str = Field(..., min_length=1)
    snippet: str = Field(default="", description="Short excerpt to show the user.")
    ldu_id: str | None = None
    table_id: str | None = None
    figure_id: str | None = None

    model_config = {"frozen": False}


# -----------------------------------------------------------------------------
# ProvenanceChain — spec 07 §7.2
# -----------------------------------------------------------------------------


class ProvenanceChain(BaseModel):
    """Full provenance for an answer. If verified=True, items must be non-empty."""

    answer_id: str = Field(..., min_length=1)
    items: list[ProvenanceItem] = Field(default_factory=list)
    verified: bool = Field(default=False, description="True when claim is backed by citations.")

    @model_validator(mode="after")
    def verified_requires_non_empty_items(self) -> "ProvenanceChain":
        if self.verified and not self.items:
            raise ValueError("ProvenanceChain: when verified=True, items must be non-empty.")
        return self

    model_config = {"frozen": False}


# -----------------------------------------------------------------------------
# Helper: attach provenance to an answer
# -----------------------------------------------------------------------------


def attach_provenance_to_answer(
    answer_text: str,
    items: list[ProvenanceItem],
    answer_id: str = "answer",
    verified: bool | None = None,
) -> tuple[str, ProvenanceChain]:
    """
    Build a ProvenanceChain from citation items and return (answer_text, chain).
    If verified is None, it is set to True when items is non-empty, else False.
    Raises if verified=True and items is empty.
    """
    if verified is None:
        verified = len(items) > 0
    chain = ProvenanceChain(answer_id=answer_id, items=items, verified=verified)
    return (answer_text, chain)


def build_provenance_chain(
    answer_id: str,
    items: list[ProvenanceItem],
    verified: bool = False,
) -> ProvenanceChain:
    """Build a ProvenanceChain. Use when you only need the chain (e.g. for audit log)."""
    return ProvenanceChain(answer_id=answer_id, items=items, verified=verified)


__all__ = [
    "ProvenanceItem",
    "ProvenanceChain",
    "attach_provenance_to_answer",
    "build_provenance_chain",
]
