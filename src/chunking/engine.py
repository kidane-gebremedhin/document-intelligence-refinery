# Semantic Chunking Engine — ExtractedDocument -> LDUs. Spec 04; Refinery Guide Stage 3.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.models import (
    BoundingBox,
    ExtractedDocument,
    Figure,
    LDU,
    LDUContentType,
    PageRef,
    RefType,
    Table,
    TextBlock,
    compute_content_hash,
)

from .validator import ChunkValidator, emit_ldus


def _token_count(text: str) -> int:
    # Cheap approximation; avoids adding tokenizer deps.
    return len((text or "").split())


_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+\S+")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]\s+|\(?\d+[\).\]]\s+|\(?[a-zA-Z][\).\]]\s+)")


def _looks_like_heading(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if len(t) <= 80 and _HEADING_RE.match(t):
        return True
    # Short ALL-CAPS lines often represent headings in extracted text.
    letters = [c for c in t if c.isalpha()]
    if letters and len(t) <= 60 and all(c.isupper() for c in letters):
        return True
    return False


def _is_list_item(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    first_line = t.splitlines()[0]
    return bool(_LIST_ITEM_RE.match(first_line))


def _bbox_union(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    return BoundingBox(
        x0=min(a.x0, b.x0),
        y0=min(a.y0, b.y0),
        x1=max(a.x1, b.x1),
        y1=max(a.y1, b.y1),
    )


def _render_table_text(table: Table) -> tuple[str, dict[str, Any]]:
    # Minimal serialization that is deterministic for hashing and useful for retrieval.
    header_rows = table.header.rows if table.header and table.header.rows else []
    header: list[str] = []
    if header_rows:
        header = [c.text for c in header_rows[0].cells]
    rows: list[list[str]] = []
    for r in table.body_rows:
        rows.append([c.text for c in r.cells])

    # Markdown-ish rendering.
    parts: list[str] = []
    if table.title:
        parts.append(table.title.strip())
    if table.caption:
        parts.append(table.caption.strip())
    if header:
        parts.append("| " + " | ".join(header) + " |")
        parts.append("| " + " | ".join(["---"] * len(header)) + " |")
    for r in rows:
        parts.append("| " + " | ".join(r) + " |")
    text = "\\n".join([p for p in parts if p])
    raw_payload: dict[str, Any] = {
        "header": header,
        "rows": rows,
    }
    if table.title:
        raw_payload["title"] = table.title
    if table.caption:
        raw_payload["caption"] = table.caption
    return text, raw_payload


def _figure_text_and_payload(fig: Figure, label: str) -> tuple[str, dict[str, Any]]:
    caption = (fig.caption or "").strip()
    alt = (fig.alt_text or "").strip()
    text = caption or alt
    raw_payload: dict[str, Any] = {"label": label}
    if fig.caption:
        raw_payload["caption"] = fig.caption
    if fig.alt_text:
        raw_payload["alt_text"] = fig.alt_text
    if fig.type:
        raw_payload["type"] = fig.type
    return text, raw_payload


@dataclass
class ChunkingEngine:
    """
    Convert ExtractedDocument to a reading-order list of LDUs and validate them.
    Enforces the chunking constitution via ChunkValidator (spec 04 §6).
    """

    max_tokens: int = 800
    reject_missing_parent_section: bool = True

    def chunk(self, doc: ExtractedDocument) -> list[LDU]:
        blocks_by_id: dict[str, TextBlock] = {b.id: b for b in doc.text_blocks}
        tables_by_id: dict[str, Table] = {t.id: t for t in doc.tables}
        figures_by_id: dict[str, Figure] = {f.id: f for f in doc.figures}

        reading = list(doc.reading_order or [])
        if reading:
            reading.sort(key=lambda e: e.order)
        else:
            # Fallback: reading order by page then index for text blocks.
            reading = sorted(
                [
                    type(
                        "E",
                        (),
                        {"ref_type": RefType.TEXT_BLOCK, "ref_id": b.id, "order": b.reading_order_index},
                    )
                    for b in doc.text_blocks
                ],
                key=lambda e: e.order,
            )

        ldus: list[LDU] = []
        current_section_id: str | None = None
        ldu_counter = 0
        table_counter = 0
        figure_counter = 0
        table_label_to_ldu_id: dict[str, str] = {}
        figure_label_to_ldu_id: dict[str, str] = {}

        i = 0
        while i < len(reading):
            entry = reading[i]
            ref_type = entry.ref_type
            ref_id = entry.ref_id

            def new_ldu_id() -> str:
                nonlocal ldu_counter
                ldu_counter += 1
                return f"ldu_{ldu_counter:04d}"

            if ref_type == RefType.TEXT_BLOCK:
                block = blocks_by_id.get(ref_id)
                if not block:
                    i += 1
                    continue
                text = (block.text or "").strip()
                if not text:
                    i += 1
                    continue

                # Heading / section header
                if _looks_like_heading(text):
                    ldu_id = new_ldu_id()
                    ldu = LDU(
                        id=ldu_id,
                        document_id=doc.document_id,
                        content_type=LDUContentType.HEADING,
                        text=text,
                        raw_payload={},
                        page_refs=[PageRef(document_id=doc.document_id, page_number=block.page_number)],
                        bounding_boxes=[block.bbox],
                        parent_section_id=None,
                        token_count=_token_count(text),
                        content_hash=compute_content_hash(LDUContentType.HEADING.value, text),
                        relationships={},
                    )
                    ldus.append(ldu)
                    current_section_id = ldu_id
                    i += 1
                    continue

                # List grouping: consecutive list-like blocks on same page.
                if _is_list_item(text):
                    page = block.page_number
                    texts = [text]
                    bbox = block.bbox
                    j = i + 1
                    while j < len(reading):
                        nxt = reading[j]
                        if nxt.ref_type != RefType.TEXT_BLOCK:
                            break
                        nb = blocks_by_id.get(nxt.ref_id)
                        if not nb or nb.page_number != page:
                            break
                        nt = (nb.text or "").strip()
                        if not nt or not _is_list_item(nt):
                            break
                        texts.append(nt)
                        bbox = _bbox_union(bbox, nb.bbox)
                        j += 1
                    merged = "\\n".join(texts)
                    ldu_id = new_ldu_id()
                    relationships: dict[str, list[str]] = {}
                    _attach_cross_refs(merged, relationships, table_label_to_ldu_id, figure_label_to_ldu_id)
                    ldus.append(
                        LDU(
                            id=ldu_id,
                            document_id=doc.document_id,
                            content_type=LDUContentType.LIST,
                            text=merged,
                            raw_payload={"list_complete": True},
                            page_refs=[PageRef(document_id=doc.document_id, page_number=page)],
                            bounding_boxes=[bbox],
                            parent_section_id=current_section_id,
                            token_count=_token_count(merged),
                            content_hash=compute_content_hash(LDUContentType.LIST.value, merged),
                            relationships=relationships,
                        )
                    )
                    i = j
                    continue

                # Paragraph
                ldu_id = new_ldu_id()
                relationships = {}
                _attach_cross_refs(text, relationships, table_label_to_ldu_id, figure_label_to_ldu_id)
                ldus.append(
                    LDU(
                        id=ldu_id,
                        document_id=doc.document_id,
                        content_type=LDUContentType.PARAGRAPH,
                        text=text,
                        raw_payload={},
                        page_refs=[PageRef(document_id=doc.document_id, page_number=block.page_number)],
                        bounding_boxes=[block.bbox],
                        parent_section_id=current_section_id,
                        token_count=_token_count(text),
                        content_hash=compute_content_hash(LDUContentType.PARAGRAPH.value, text),
                        relationships=relationships,
                    )
                )
                i += 1
                continue

            if ref_type == RefType.TABLE:
                table = tables_by_id.get(ref_id)
                if not table:
                    i += 1
                    continue
                table_counter += 1
                label = f"Table {table_counter}"
                text, payload = _render_table_text(table)
                payload["label"] = label
                ldu_id = new_ldu_id()
                ldus.append(
                    LDU(
                        id=ldu_id,
                        document_id=doc.document_id,
                        content_type=LDUContentType.TABLE,
                        text=text or label,
                        raw_payload=payload,
                        page_refs=[PageRef(document_id=doc.document_id, page_number=table.page_number)],
                        bounding_boxes=[table.bbox],
                        parent_section_id=current_section_id,
                        token_count=_token_count(text),
                        content_hash=compute_content_hash(LDUContentType.TABLE.value, text, payload),
                        relationships={},
                    )
                )
                table_label_to_ldu_id[label] = ldu_id
                i += 1
                continue

            if ref_type == RefType.FIGURE:
                fig = figures_by_id.get(ref_id)
                if not fig:
                    i += 1
                    continue
                figure_counter += 1
                label = f"Figure {figure_counter}"
                text, payload = _figure_text_and_payload(fig, label)
                ldu_id = new_ldu_id()

                # Only emit as FIGURE when we have some descriptive text (caption or alt_text).
                # Otherwise keep as OTHER to avoid validator rejection (caption missing).
                if text:
                    content_type = LDUContentType.FIGURE
                    content_hash = compute_content_hash(LDUContentType.FIGURE.value, text, payload)
                else:
                    content_type = LDUContentType.OTHER
                    content_hash = compute_content_hash(LDUContentType.OTHER.value, label, payload)

                ldus.append(
                    LDU(
                        id=ldu_id,
                        document_id=doc.document_id,
                        content_type=content_type,
                        text=text or label,
                        raw_payload=payload,
                        page_refs=[PageRef(document_id=doc.document_id, page_number=fig.page_number)],
                        bounding_boxes=[fig.bbox],
                        parent_section_id=current_section_id,
                        token_count=_token_count(text or label),
                        content_hash=content_hash,
                        relationships={},
                    )
                )
                figure_label_to_ldu_id[label] = ldu_id
                i += 1
                continue

            # Unknown entry type
            i += 1

        validator = ChunkValidator(reject_missing_parent_section=self.reject_missing_parent_section)
        return emit_ldus(ldus, validator=validator)


_TABLE_REF_RE = re.compile(r"\bTable\s+(\d+)\b", re.IGNORECASE)
_FIG_REF_RE = re.compile(r"\bFigure\s+(\d+)\b", re.IGNORECASE)


def _attach_cross_refs(
    text: str,
    relationships: dict[str, list[str]],
    table_label_to_ldu_id: dict[str, str],
    figure_label_to_ldu_id: dict[str, str],
) -> None:
    """Best-effort cross-reference resolution. Spec 04 R5 (non-blocking)."""
    if not text:
        return
    for m in _TABLE_REF_RE.finditer(text):
        label = f"Table {m.group(1)}"
        target = table_label_to_ldu_id.get(label)
        if target:
            relationships.setdefault("references_table", []).append(target)
    for m in _FIG_REF_RE.finditer(text):
        label = f"Figure {m.group(1)}"
        target = figure_label_to_ldu_id.get(label)
        if target:
            relationships.setdefault("references_figure", []).append(target)

