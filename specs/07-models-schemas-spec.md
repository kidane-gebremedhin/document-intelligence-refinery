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

LDUs are the **RAG-ready semantic units** produced by the Chunking Engine.

### 5.1 `LDUContentType`

- **Type**
  - `str` (enum)

- **Allowed Values**
  - `"paragraph"`
  - `"section_intro"`
  - `"table"`
  - `"table_section"` (e.g., a subset of a large table grouped logically)
  - `"figure"`
  - `"list"`
  - `"footnote"`
  - `"other"`

---

### 5.2 `LDU`

- **Fields**
  - `id: str`
    - Unique within a document.
  - `document_id: str`
  - `content_type: LDUContentType`
  - `text: str`
    - Main textual payload. For tables/figures, this may be a textual representation or summary.
  - `raw_payload: dict[str, Any]`
    - Structured payload when `content_type` is not purely text (e.g., table matrix, figure metadata).
  - `page_refs: list[PageRef]`
    - One or more pages this LDU spans or references.
  - `bounding_boxes: list[BoundingBox]`
    - One or more bboxes that this LDU aggregates (e.g., multiple rows of a table).
  - `parent_section_id: str | None`
    - Link to a PageIndex section node, if known.
  - `token_count: int`
    - Approximate token length for LLM budgeting.
  - `content_hash: str`
    - Stable hash of canonicalized content for provenance.
  - `relationships: dict[str, list[str]]`
    - e.g., `{ "references_tables": ["table_3"], "references_figures": ["figure_2"] }`.

- **Invariants**
  - A table LDU must include complete header + associated rows; must not represent a “half table”.
  - A figure LDU must preserve its caption inside `text` or `raw_payload`.
  - Each LDU must have at least one `page_ref` and one `bounding_box`.

---

## 6. `PageIndex` & `PageIndexSection`

The PageIndex is a tree of sections enabling hierarchical navigation.

### 6.1 `PageIndexSection`

- **Fields**
  - `id: str`
  - `document_id: str`
  - `title: str`
  - `level: int`
    - e.g., 1 for top-level, 2 for sub-section, etc.
  - `page_span: PageSpan`
  - `child_sections: list[PageIndexSection]`
  - `key_entities: list[str]`
    - e.g., organization names, financial metrics, topics.
  - `summary: str`
    - 2–3 sentence LLM-generated summary of the section.
  - `data_types_present: list[str]`
    - Allowed values: `"tables"`, `"figures"`, `"equations"`, `"lists"`, `"paragraphs"`.
  - `linked_ldu_ids: list[str]`
    - IDs of LDUs primarily associated with this section.

- **Invariants**
  - `level` must be consistent with parent-child relationships (child level = parent level + 1).
  - `page_span.document_id` must match `document_id`.

---

### 6.2 `PageIndex`

- **Fields**
  - `document_id: str`
  - `root_sections: list[PageIndexSection]`
  - `created_at: datetime`
  - `metadata: dict[str, Any]` (optional)

- **Invariants**
  - All `PageIndexSection.document_id` must equal `PageIndex.document_id`.
  - Tree must be acyclic and connected (no orphan sections).

---

## 7. Provenance Models

Every answer must be backed by provenance that can be audited.

### 7.1 `ProvenanceItem`

- **Fields**
  - `document_id: str`
  - `document_name: str`
  - `page_number: int`
  - `bbox: BoundingBox`
  - `content_hash: str`
  - `snippet: str`
    - Short text excerpt to show the human.
  - `ldu_id: str | None`
    - If the answer is derived from a specific LDU.
  - `table_id: str | None`
  - `figure_id: str | None`

---

### 7.2 `ProvenanceChain`

Represents the full provenance for a given answer.

- **Fields**
  - `answer_id: str`
  - `items: list[ProvenanceItem]`

- **Invariants**
  - `items` must be non-empty for claim-marked-as-verified.
  - If no items are found, the system must explicitly label the claim as `"unverifiable"` at the application layer.

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