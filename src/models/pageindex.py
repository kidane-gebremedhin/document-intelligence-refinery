# PageIndex and PageIndexSection — hierarchical navigation. Spec 07 §6.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import PageSpan


class PageIndexSection(BaseModel):
    """One section node in the PageIndex tree (title, page range, summaries, linked LDUs)."""

    id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    title: str = Field(default="")
    level: int = Field(..., ge=1, description="1 = top-level, 2 = sub-section, etc.")
    page_span: PageSpan = Field(...)
    child_sections: list[PageIndexSection] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    summary: str = Field(default="")
    data_types_present: list[str] = Field(default_factory=list)
    linked_ldu_ids: list[str] = Field(default_factory=list, description="LDUs in this section.")

    model_config = {"frozen": False}


class PageIndex(BaseModel):
    """Per-document hierarchical navigation tree (root_sections)."""

    document_id: str = Field(..., min_length=1)
    root_sections: list[PageIndexSection] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def document_id_consistent(self) -> "PageIndex":
        for sec in self._all_sections():
            if sec.document_id != self.document_id:
                raise ValueError(
                    f"PageIndexSection {sec.id!r} document_id must equal PageIndex.document_id"
                )
        return self

    def _all_sections(self) -> list[PageIndexSection]:
        out: list[PageIndexSection] = []
        for s in self.root_sections:
            out.append(s)
            out.extend(self._descendants(s))
        return out

    def _descendants(self, section: PageIndexSection) -> list[PageIndexSection]:
        out: list[PageIndexSection] = []
        for c in section.child_sections:
            out.append(c)
            out.extend(self._descendants(c))
        return out

    model_config = {"frozen": False}


__all__ = ["PageIndex", "PageIndexSection"]
