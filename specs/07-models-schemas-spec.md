# Spec 07 – Data Model Schemas (`src/models/`)

## 1. Purpose & Scope

This document defines the **conceptual schemas** for all core data models used by the Document Intelligence Refinery.  
These schemas are the source of truth for the Pydantic models that will be implemented in `src/models/`.

They must support:

- The 5-stage pipeline:
  - Triage Agent
  - Multi-Strategy Extraction Engine
  - Semantic Chunking Engine
  - PageIndex Builder
  - Query Interface Agent
- All deliverables described in the Week 3 challenge:
  - `DocumentProfile`
  - `ExtractedDocument`
  - `LDU` (Logical Document Unit)
  - `PageIndex`
  - `ProvenanceChain`
- Auxiliary structures required for:
  - Spatial provenance (bbox + page)
  - Extraction ledger entries
  - Fact table extraction
  - Configuration-driven behavior

This spec describes **fields, types, relationships, and invariants** but **does not prescribe concrete Python syntax**.

---

## 2. Shared Value Objects

These are small, reusable value types used across multiple models.

### 2.1 `BoundingBox`

Represents a rectangular region on a PDF page.

- **Fields**
  - `x0: float`  
    - Left coordinate in PDF points (origin: bottom-left of page).
  - `y0: float`  
    - Bottom coordinate.
  - `x1: float`  
    - Right coordinate.
  - `y1: float`  
    - Top coordinate.

- **Constraints**
  - `x0 < x1`, `y0 < y1`.
  - Coordinates must be relative to the original page size; if normalized coordinates are needed, they should be derived properties, not stored.

---

### 2.2 `PageRef`

Represents a reference to a single page in a document.

- **Fields**
  - `document_id: str`
  - `page_number: int`  
    - 1-based index.

- **Constraints**
  - `page_number >= 1`.

---

### 2.3 `PageSpan`

Represents a range of pages (inclusive).

- **Fields**
  - `document_id: str`
  - `page_start: int`
  - `page_end: int`

- **Constraints**
  - `page_start >= 1`
  - `page_end >= page_start`.

---

### 2.4 `LanguageCode`

- **Type**
  - `str` (BCP-47 or ISO-like, e.g., `"en"`, `"am"`, `"fr"`).
- **Constraints**
  - Must be lowercase, 2–5 characters.
  - Confidence attached in higher-level models, not here.

---

## 3. `DocumentProfile`

The output of the Triage Agent; governs extraction strategy selection.

- **Fields**
  - `document_id: str`  
    - Stable ID for the document; used as key in `.refinery/profiles`.
  - `origin_type: str` (enum)
    - Allowed values:
      - `"native_digital"`
      - `"scanned_image"`
      - `"mixed"`
      - `"form_fillable"`
  - `layout_complexity: str` (enum)
    - Allowed values:
      - `"single_column"`
      - `"multi_column"`
      - `"table_heavy"`
      - `"figure_heavy"`
      - `"mixed"`
  - `language: LanguageCode`
  - `language_confidence: float`
    - Range: `0.0–1.0`.
  - `domain_hint: str` (enum)
    - Allowed values:
      - `"financial"`
      - `"legal"`
      - `"technical"`
      - `"medical"`
      - `"general"`
  - `estimated_extraction_cost: str` (enum)
    - Allowed values:
      - `"fast_text_sufficient"`
      - `"needs_layout_model"`
      - `"needs_vision_model"`
  - `triage_confidence_score: float`
    - Aggregate confidence in the classification; `0.0–1.0`.
  - `created_at: datetime`
  - `metadata: dict[str, Any]` (optional)
    - Free-form extra signals (e.g., character_density, image_area_ratio).

- **Invariants**
  - `document_id` must match filenames used in `.refinery/profiles/{document_id}.json`.
  - `estimated_extraction_cost` must be consistent with `origin_type` and `layout_complexity` according to the triage rules.

---

## 4. `ExtractedDocument` and Subtypes

`ExtractedDocument` is the **normalized internal representation** that all extraction strategies (FastText, Layout, Vision) must produce.

### 4.1 `TextBlock`

Represents a contiguous block of text with spatial information.

- **Fields**
  - `id: str`  
    - Unique within a document.
  - `document_id: str`
  - `page_number: int`
  - `bbox: BoundingBox`
  - `text: str`
  - `reading_order_index: int`
    - Defines ordering relative to other blocks on same page.
  - `style: dict[str, Any]` (optional)
    - e.g., font_size, bold, italic, heading_level.
  - `section_hint: str | None`
    - Optional, e.g., inferred section title.

---

### 4.2 `TableCell`

- **Fields**
  - `row_index: int`
  - `col_index: int`
  - `text: str`
  - `bbox: BoundingBox | None`
  - `rowspan: int` (default = 1)
  - `colspan: int` (default = 1)

---

### 4.3 `TableRow`

- **Fields**
  - `index: int`
  - `cells: list[TableCell]`

---

### 4.4 `TableHeader`

- **Fields**
  - `rows: list[TableRow]`
  - `bbox: BoundingBox | None`

---

### 4.5 `Table`

Represents a structured table extracted from the document.

- **Fields**
  - `id: str`
  - `document_id: str`
  - `page_number: int`
  - `bbox: BoundingBox`
  - `title: str | None`
  - `caption: str | None`
  - `header: TableHeader | None`
  - `body_rows: list[TableRow]`
  - `source_text_block_ids: list[str]` (optional)
    - Back-reference to underlying text blocks used in extraction.

- **Invariants**
  - Table header + body must be structurally consistent (same logical column count, considering colspans).
  - No `TableCell` may straddle multiple LDUs once chunked.

---

### 4.6 `Figure`

Represents a figure or image region.

- **Fields**
  - `id: str`
  - `document_id: str`
  - `page_number: int`
  - `bbox: BoundingBox`
  - `caption: str | None`
  - `type: str` (optional)
    - e.g., `"chart"`, `"photo"`, `"diagram"`.
  - `alt_text: str | None`
    - Optional textual description for accessibility / semantic search.

---

### 4.7 `ExtractedDocument`

Top-level container for extracted structure.

- **Fields**
  - `document_id: str`
  - `source_path: str` (optional)
  - `pages: int`
  - `text_blocks: list[TextBlock]`
  - `tables: list[Table]`
  - `figures: list[Figure]`
  - `metadata: dict[str, Any]`
    - e.g., title, author, creation_date, any model-specific metadata.
  - `strategy_used: str`
    - `"fast_text" | "layout" | "vision"`.
  - `strategy_confidence: float`
    - `0.0–1.0`.

- **Invariants**
  - All referenced `page_number` values must be between `1` and `pages`.
  - `document_id` must match the triage profile’s `document_id`.

---

## 5. `LDU` – Logical Document Unit

LDUs are the **RAG-ready semantic units** produced by the Chunking Engine. Per [04 – Semantic Chunking & LDUs](04-semantic-chunking-and-ldu-spec.md), every LDU **must** include: **content**, **chunk_type**, **page_refs**, **bounding_boxes**, **parent_section**, **token_count**, **content_hash**, and **relationships**. These fields are required for Phase 3 and for downstream stages (PageIndex, vector store, provenance).

### 5.1 `LDUContentType` / `chunk_type`

- **Type**
  - `str` (enum); spec 04 uses `chunk_type`; implementations may use either name so long as the set is consistent.

- **Allowed Values** (aligned with spec 04 §4.3)
  - `"paragraph"`
  - `"heading"`
  - `"table"`
  - `"figure"`
  - `"list"`
  - `"section_header"`
  - `"caption"`
  - `"other"`
  - Optional extensions: `"section_intro"`, `"table_section"`, `"footnote"` (map to spec 04 types as needed).

---

### 5.2 `LDU`

- **Fields (required set for Phase 3)**

  | Field | Type | Required | Description |
  |-------|------|----------|-------------|
  | `id` | `str` | Yes | Unique within a document; stable for provenance. |
  | `document_id` | `str` | Yes | Same as ExtractedDocument. |
  | `content` | `str` | Yes | Main textual payload. For tables: serialized table (header + rows). For figures: caption/alt text. Align with spec 04 `content`. |
  | `chunk_type` | enum (see §5.1) | Yes | Semantic type: paragraph, heading, table, figure, list, section_header, caption, other. |
  | `page_refs` | `list[int]` | Yes | 1-based page numbers; non-empty. For multi-page LDUs, list all pages. |
  | `bounding_boxes` | `list[BoundingBox]` | Yes | One bbox per page (same order as `page_refs`); non-empty. Single-page = one element. |
  | `parent_section` | `str \| None` | No | Section header or section ID containing this LDU. |
  | `token_count` | `int` | Yes | Approximate token count of `content`. |
  | `content_hash` | `str` | Yes | Stable hash of canonicalized content (spec 04 §7). Non-empty. |
  | `relationships` | `list[Relationship]` | No | References to other LDUs (e.g. "see Table 3" → target LDU id). See §5.3. |

- **Optional / legacy**
  - `text` — May alias or derive from `content` for compatibility.
  - `raw_payload: dict[str, Any]` — Optional structured payload (e.g. table matrix); not required for Phase 3.

- **Invariants**
  - `page_refs` non-empty; `bounding_boxes` non-empty and length consistent with `page_refs` (one per page or single bbox for single-page).
  - Table LDU: must include complete header + associated rows (no "half table"); see spec 04 Rule 1.
  - Figure LDU: caption must be in the same LDU (spec 04 Rule 2).
  - List LDU: no mid-item split (spec 04 Rule 3).
  - `content_hash` must be computed per spec 04 §7 (canonicalization rules).

---

### 5.3 `Relationship` (LDU cross-reference)

- **Fields**
  - `target_ldu_id: str | None`
    - ID of the referenced LDU; null if unresolved.
  - `relation_type: str`
    - e.g. `references_table`, `references_figure`, `references_section`, `references_clause`, `other`.
  - `anchor_text: str | None`
    - The referring text (e.g. "Table 3", "Section 4.2").

---

### 5.4 Chunk validation (ChunkValidator)

The Chunking Engine must run a **ChunkValidator** before emitting LDUs. The validator enforces the five chunking rules as hard constraints (spec 04 §5, §6). Validation result and error types are part of the model surface for tests and pipeline integration.

- **ValidationResult** (conceptual)
  - `valid: bool` — True iff all checks passed.
  - `errors: list[ChunkValidationError]` — Non-empty when `valid` is False.

- **ChunkValidationError**
  - `code: str` — One of: `TABLE_HEADER_CELLS_SPLIT`, `FIGURE_CAPTION_NOT_UNIFIED`, `LIST_MID_ITEM_SPLIT`, `PARENT_SECTION_MISSING`, `PAGE_REFS_EMPTY`, `BOUNDING_BOXES_INVALID`, `CONTENT_HASH_MISSING`.
  - `ldu_ids: list[str] | None` — IDs of offending LDUs, when applicable.
  - `message: str | None` — Human-readable description.

- **Invariants**
  - If the validator returns `valid=False`, the pipeline must not pass the candidate list of LDUs to Stage 4.
  - Same input list must produce the same validation result (deterministic).

---

## 6. `PageIndex` & `PageIndexSection`

The PageIndex is a tree of sections enabling hierarchical navigation. Per [05 – PageIndex Builder](05-pageindex-builder-spec.md), each section node must support: **title**, **page_start** / **page_end**, **child_sections**, **key_entities**, **summary** (LLM-generated 2–3 sentences when used), **data_types_present**, and **ldu_ids**. The PageIndex is persisted to **`.refinery/pageindex/{document_id}.json`**.

### 6.1 `PageIndexSection`

Section tree node; aligns with spec 05 §3.2.

- **Fields (Phase 3 required set)**

  | Field | Type | Required | Description |
  |-------|------|----------|-------------|
  | `id` | `str` | Yes | Unique within the document (e.g. `sec_001`, path `1.2.3`). |
  | `document_id` | `str` | Yes | Same as PageIndex. |
  | `title` | `str` | Yes | Section title (e.g. "3.2 Financial Performance"; root may be "Document"). |
  | `page_start` | `int` | Yes | 1-based page where the section begins. |
  | `page_end` | `int` | Yes | 1-based page where the section ends. Invariant: `page_end >= page_start`. |
  | `child_sections` | `list[PageIndexSection]` | Yes | Child sections; empty for leaves. In document order by `page_start`. |
  | `key_entities` | `list[str]` | No | Named entities in this section (organizations, dates, metrics). For topic scoring. |
  | `summary` | `str \| None` | No | LLM-generated 2–3 sentence summary. Null when summarization disabled or failed. |
  | `data_types_present` | `list[str]` | No | Content types: `"tables"`, `"figures"`, `"equations"`, `"lists"`, `"paragraphs"`. |
  | `ldu_ids` | `list[str]` | No | IDs of LDUs in this section. Required for retrieval narrowing after pageindex_query. |

- **Optional**
  - `level: int` — Nesting level (0 = root, 1 = top-level). May be derived from tree position.
  - `page_span: PageSpan` — May be used in place of or derived from `page_start`/`page_end`; spec 05 uses page_start/page_end.

- **Invariants**
  - For every section, `page_start <= page_end`; both in `[1, page_count]` of the document.
  - Child section `[page_start, page_end]` must be within parent's range.
  - Sibling sections ordered by `page_start`; ranges do not overlap (or only at boundaries).
  - `document_id` must match `PageIndex.document_id`.

---

### 6.2 `PageIndex`

Top-level container; one per document. Persisted to `.refinery/pageindex/{document_id}.json` per spec 05 §8.

- **Fields**

  | Field | Type | Required | Description |
  |-------|------|----------|-------------|
  | `document_id` | `str` | Yes | Document identifier; matches LDU document_id and file path. |
  | `page_count` | `int` | Yes | Total pages in the document. |
  | `root` | `PageIndexSection` | Yes | Single root section (tree root). Spans `page_start=1`, `page_end=page_count`. |
  | `built_at` | `datetime \| str` | No | When the index was built (ISO 8601 or datetime). |
  | `metadata` | `dict[str, Any]` | No | Optional extra fields. |

- **Alternative shape:** Implementations may use `root_sections: list[PageIndexSection]` (top-level sections under an implicit root); persisted JSON must still satisfy spec 05 §8 (document_id, page_count, root or equivalent, round-trip).

- **Invariants**
  - Tree is acyclic and connected; no orphan sections.
  - All `PageIndexSection.document_id` equal `PageIndex.document_id`.
  - Serialization: must be persistable to `.refinery/pageindex/{document_id}.json` as JSON; load and re-serialize yields equivalent structure.

---

## 7. Provenance Models

Every answer from the Query Interface Agent must be backed by a **ProvenanceChain** that can be audited. Per [06 – Query Agent & Provenance](06-query-agent-and-provenance-spec.md), each citation (ProvenanceItem) must include **document_name**, **page_number**, **bbox**, and **content_hash** (for LDU-backed sources). Audit mode requires that claim verification yields either citations or an explicit **unverifiable** flag—never fake verification.

### 7.1 `ProvenanceItem` (Citation)

Single source citation; aligns with spec 06 §4.2.

- **Fields (required for every answer)**

  | Field | Type | Required | Description |
  |-------|------|----------|-------------|
  | `document_id` | `str` | Yes | Stable document identifier. |
  | `document_name` | `str` | Yes | Human-readable name (e.g. filename, report title). |
  | `page_number` | `int` | Yes | 1-based page where the cited content appears. |
  | `bbox` | `BoundingBox \| None` | Yes for LDU | Spatial coordinates. Required for LDU-backed citations; may be null for FactTable-only when not stored. |
  | `content_hash` | `str` | Yes for LDU | Stable hash of source content. Required for LDU-backed; optional for FactTable when not resolvable. |
  | `snippet` | `str \| None` | No | Short excerpt for display. |
  | `ldu_id` | `str \| None` | No | LDU identifier when from LDU. |
  | `table_id` | `str \| None` | No | Optional table reference. |
  | `figure_id` | `str \| None` | No | Optional figure reference. |

- **Invariants**
  - For LDU-backed citations: `document_name`, `document_id`, `page_number`, `bbox`, `content_hash` must be present and non-empty (where applicable).
  - No citation may be emitted with missing required fields for its source type.

---

### 7.2 `ProvenanceChain`

Represents the full provenance for a given answer. Every answer must include a ProvenanceChain.

- **Fields**

  | Field | Type | Required | Description |
  |-------|------|----------|-------------|
  | `answer_id` | `str` | Yes | Identifier for the answer (e.g. query id or run id). |
  | `items` | `list[ProvenanceItem]` | Yes | Citations; one per distinct source. Empty when audit result is unverifiable. |
  | `verification_status` | `str \| None` | No | For audit mode: `verified` \| `partial` \| `unverifiable`. See below. |

- **Verification flags (audit mode)**
  - **verified** — At least one citation supports the claim. `items` is non-empty. Use only when a real source was found.
  - **unverifiable** — No supporting source found. `items` must be **empty**. No invented citations. The system must never mark as verified without citations.
  - **partial** — Optional; only part of a compound claim is supported; remainder unverifiable.

- **Invariants**
  - For claim-marked-as-**verified**: `items` must be non-empty; every item has required fields (document_name, page_number, bbox for LDU, content_hash for LDU).
  - For claim-marked-as-**unverifiable**: `items` must be empty; `verification_status` = `unverifiable`. The application layer must never return a citation when the claim could not be verified (no fake verification).
  - Every answer carries a ProvenanceChain; when no sources exist (e.g. no retrieval results), the chain may have empty items and optionally verification_status or a clear "no sources" signal.

---

### 7.3 `QAExample` / Query–Answer pair (conceptual)

For logging, evaluation, or acceptance artifacts, a **query–answer pair** can be represented as a small structure that combines the answer text with its provenance and (in audit mode) verification outcome. This is not required for the runtime API but supports Phase 4 acceptance (e.g. "example Q&A with ProvenanceChain").

- **Conceptual fields**
  - `query: str` — The user question or claim (for audit).
  - `answer: str` — The agent’s answer text.
  - `provenance: ProvenanceChain` — Citations (document_name, page_number, bbox, content_hash) and optional `verification_status`.
  - `verification_status` — When in audit mode: `verified` (with citations) or `unverifiable` (no citations). Never fake verification.

Implementations may use a Pydantic model or a simple dict; the spec only requires that every answer includes a ProvenanceChain and that audit mode uses verification flags as above.

---

## 8. Fact Table Models (Numerical Fact Extraction)

The system must extract structured numerical facts for precise querying.

### 8.1 `FactRecord`

Represents one atomic fact inserted into SQLite.

- **Fields**
  - `id: str`
  - `document_id: str`
  - `entity: str`
    - e.g., `"total_revenue"`, `"capital_expenditure"`.
  - `value: float`
  - `unit: str | None`
    - e.g., `"USD"`, `"ETB"`, `"percent"`.
  - `period: str | None`
    - e.g., `"Q3 2024"`, `"FY 2022"`.
  - `category_path: list[str]`
    - Hierarchical categories, e.g., `["Income Statement", "Revenue", "Interest Income"]`.
  - `source_page: int`
  - `source_bbox: BoundingBox`
  - `source_content_hash: str`
  - `metadata: dict[str, Any]` (optional)
    - e.g., original cell text, table id.

- **Invariants**
  - `document_id` and `source_content_hash` must be sufficient to re-link to the originating LDU/table.

---

## 9. Extraction Ledger Entry

The extraction ledger tracks strategy, confidence, and cost per document.

### 9.1 `ExtractionLedgerEntry`

- **Fields**
  - `document_id: str`
  - `strategy_used: str`
    - `"fast_text" | "layout" | "vision"`.
  - `origin_type: str`
  - `layout_complexity: str`
  - `start_time: datetime`
  - `end_time: datetime`
  - `processing_time_ms: int`
  - `confidence_score: float`
    - Aggregate confidence in the final extraction.
  - `cost_estimate_usd: float`
  - `token_usage_prompt: int | None`
  - `token_usage_completion: int | None`
  - `escalation_chain: list[str]`
    - e.g., `["fast_text", "layout"]` if escalation occurred.
  - `notes: str | None`

- **Invariants**
  - `end_time >= start_time`.
  - `strategy_used` must be the last item in `escalation_chain`.

---

## 10. Configuration Model (Optional, Conceptual)

Although thresholds will primarily live in `rubric/extraction_rules.yaml`, a conceptual `ExtractionRulesConfig` model can be used internally.

### 10.1 `ExtractionRulesConfig` (Conceptual)

- **Fields**
  - `min_chars_per_page: int`
  - `max_image_area_ratio: float`
  - `fast_text_confidence_threshold: float`
  - `layout_confidence_threshold: float`
  - `max_tokens_per_document_for_vlm: int`
  - `chunking_rules: dict[str, Any]`
    - e.g., allowed max tokens per LDU, special cases for lists and tables.

---

## 11. General Invariants & Design Notes

- All models must be **fully typed and Pydantic-based** in implementation.
- Spatial provenance (`BoundingBox + page_number + content_hash`) is mandatory for any model contributing to answers or fact tables.
- All document-scoped models (`DocumentProfile`, `ExtractedDocument`, `LDU`, `PageIndex`, `ProvenanceChain`, `FactRecord`, `ExtractionLedgerEntry`) must share a stable `document_id`.
- Models should be designed so that a **new document type can be onboarded** by changing configuration and routing logic, without changing schemas.

This spec is the authoritative reference for the implementation of `src/models/`.
Any divergence in code must be justified and reflected back into this document.