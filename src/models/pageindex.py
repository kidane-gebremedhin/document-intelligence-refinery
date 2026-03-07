# PageIndex and PageIndexSection — hierarchical navigation. Spec 05 §3, §8; spec 07 §6.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import PageSpan


class PageIndexSection(BaseModel):
    """One section node in the PageIndex tree. Spec 05 §3.2; spec 07 §6.1."""

    id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    title: str = Field(default="")
    level: int = Field(..., ge=0, description="0 = root, 1 = top-level section, etc.")
    page_start: int = Field(..., ge=1, description="1-based page where section begins.")
    page_end: int = Field(..., ge=1, description="1-based page where section ends (inclusive).")
    child_sections: list[PageIndexSection] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    summary: str | None = Field(default=None, description="LLM summary when used; null when stubbed or failed.")
    data_types_present: list[str] = Field(default_factory=list, description="e.g. tables, figures, lists.")
    ldu_ids: list[str] = Field(default_factory=list, description="LDU ids in this section for retrieval narrowing.")

    @model_validator(mode="after")
    def page_end_ge_start(self) -> "PageIndexSection":
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        return self

    @property
    def page_span(self) -> PageSpan:
        """PageSpan for compatibility; derived from page_start, page_end."""
        return PageSpan(document_id=self.document_id, page_start=self.page_start, page_end=self.page_end)

    model_config = {"frozen": False}


class PageIndex(BaseModel):
    """Per-document PageIndex with single root section. Spec 05 §3.1, §8; spec 07 §6.2."""

    document_id: str = Field(..., min_length=1)
    page_count: int = Field(..., ge=1, description="Total pages in the document.")
    root: PageIndexSection = Field(..., description="Single root section (tree root).")
    built_at: datetime | None = Field(default=None, description="ISO 8601 when built; optional.")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def document_id_consistent(self) -> "PageIndex":
        for sec in self._all_sections():
            if sec.document_id != self.document_id:
                raise ValueError(
                    f"PageIndexSection {sec.id!r} document_id must equal PageIndex.document_id"
                )
        return self

    @property
    def root_sections(self) -> list[PageIndexSection]:
        """Top-level sections (children of root). For backward compatibility."""
        return self.root.child_sections

    def _all_sections(self) -> list[PageIndexSection]:
        out: list[PageIndexSection] = [self.root]
        out.extend(self._descendants(self.root))
        return out

    def _descendants(self, section: PageIndexSection) -> list[PageIndexSection]:
        out: list[PageIndexSection] = []
        for c in section.child_sections:
            out.append(c)
            out.extend(self._descendants(c))
        return out

    model_config = {"frozen": False}


__all__ = ["PageIndex", "PageIndexSection"]
