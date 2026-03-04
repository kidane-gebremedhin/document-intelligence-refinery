# Spec: Stage 3 – Semantic Chunking Engine & Logical Document Units (LDUs)

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Upstream:** [02 – Triage Agent & DocumentProfile](02-triage-agent-and-document-profile.md), [03 – Multi-Strategy Extraction Engine](03-multi-strategy-extraction-engine.md)  
**Constitution alignment:** Document-aware chunking (structure-respecting boundaries); spatial provenance on every LDU (page + bbox); typed Pydantic contracts; config-over-code for chunking rules and limits.

---

## 1. Purpose

Naive token-count chunking is **unacceptable** for RAG because it severs logical units and produces hallucinated answers. The Semantic Chunking Engine exists to convert raw extraction into **Logical Document Units (LDUs)**—semantically coherent, self-contained units that respect document structure.

### Why token-boundary chunking fails

| Content type | Failure mode | Consequence |
|--------------|--------------|-------------|
| **Tables** | A 512-token boundary bisects a financial table—header row in one chunk, cells in another. Cell semantics are lost; the header is severed from its data. | Every query about that table returns incomplete or nonsensical context. LLMs infer relationships that do not exist or hallucinate values. |
| **Figures** | A figure and its caption are split across chunks. The caption ("Figure 3: Revenue growth by region") lives in one LDU; the chart reference in another. | Retrieval returns the figure without context or the caption without the figure. "What does Figure 3 show?" cannot be answered correctly. |
| **Legal clauses** | A clause is severed from its antecedent or conditional ("Notwithstanding the foregoing…" is in chunk A; "the obligations under Section 4.2" is in chunk B). | Legal interpretation depends on full context. Split clauses produce wrong answers, especially for "what are the exceptions?" or "when does X apply?" queries. |
| **Numbered lists** | List items are split mid-list; item 5 is in chunk A, item 6 in chunk B, or items 1–3 in one chunk and 4–7 in another with no header. | List semantics (enumeration, hierarchy) are destroyed. "What is the third finding?" returns wrong or partial context. |

The Refinery Guide calls this **Context Poverty**: "Naive chunking for RAG severs logical units. A table split across chunks, a figure separated from its caption, a clause severed from its antecedent—all produce hallucinated answers." The Chunking Engine exists to eliminate this failure mode by enforcing structure-respecting boundaries before any token limit is applied.

---

## 2. Inputs (ExtractedDocument)

The Chunking Engine consumes a **ExtractedDocument** produced by Stage 2 (Multi-Strategy Extraction Engine). The ExtractedDocument must be the normalized representation that all three extraction strategies (fast text, layout, vision) output. No partial or malformed ExtractedDocument may be passed; invalid input must fail fast with a clear error.

### Required fields and structure

| Field | Type | Description |
|-------|------|-------------|
| **document_id** | string | Stable identifier; correlates with DocumentProfile and extraction ledger. |
| **strategy_used** | enum | `fast_text` \| `layout` \| `vision` — Which strategy produced this output. |
| **page_count** | integer | Number of pages. |
| **text_blocks** | list of TextBlock | Ordered sequence of text blocks (paragraphs, headings, list items). Each must have: `id`, `content`, `page`, `bbox`, optional `block_type` (paragraph, heading, list_item, caption, other). |
| **tables** | list of Table | Structured tables with headers and rows. Each must have: `id`, `page`, `bbox`, `headers`, `rows`, `num_rows`, `num_cols`, optional `caption`. |
| **figures** | list of Figure | Figures with optional captions. Each must have: `id`, `page`, `bbox`, optional `caption`, optional `alt_text`. |
| **reading_order** | list of ReadingOrderEntry | Logical reading order of content. Each entry: `ref_type` (text_block \| table \| figure), `ref_id`, `order`. |

### Invariants (pre-conditions)

- Every element in `text_blocks`, `tables`, `figures` has non-null `page` and `bbox`.
- `reading_order` is consistent with IDs in the referenced collections.
- Tables have at least one row; headers may be empty if not detectable.
- Figures that have captions store the caption in the figure object (constitution: caption with parent).

The Chunking Engine **traverses** ExtractedDocument in **reading order** to form LDUs. It does **not** re-order or invent structure; it uses the existing reading order and element types to apply chunking rules.

---

## 3. Outputs (List of LDUs)

### What an LDU is (conceptual)

A **Logical Document Unit (LDU)** is a minimal, semantically coherent unit of document content that:

1. **Respects structural boundaries** — Never splits a table header from its cells, a figure from its caption, a numbered list mid-list, or a legal clause from its antecedent.
2. **Is self-contained for retrieval** — An LDU can be returned by vector search and consumed by an LLM with sufficient context to answer a query about that unit without needing adjacent LDUs.
3. **Carries full provenance** — Every LDU has `page_refs` and `bounding_box` (or equivalent spatial reference) so the source location in the document can be cited.
4. **May reference other LDUs** — Cross-references (e.g., "see Table 3") are resolved and stored as `relationships`, linking LDUs semantically.
5. **Is bounded by token limits** — If a structural unit (e.g., a very long paragraph or list) exceeds `max_tokens`, it may be split only at allowed boundaries (e.g., list item boundaries), never mid-sentence or mid-cell.

The output of the Chunking Engine is a **list of LDUs** in reading order. This list is consumed by Stage 4 (PageIndex Builder) and Stage 5 (Query Interface) for indexing, vector embedding, and retrieval.

---

## 4. LDU Schema & Types

Each LDU is a typed record with the following fields. Implementations use Pydantic or equivalent; this spec defines the logical schema.

### 4.1 Core fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **id** | string | Yes | Unique identifier within the document (e.g. `ldu_001`, UUID). Stable for provenance and deduplication. |
| **content** | string | Yes | The text (or structured text representation) of the chunk. For tables: serialized table (e.g. markdown, JSON, or tab-separated) including header row and cells. For figures: alt text or caption; the figure itself is referenced, not embedded. |
| **chunk_type** | enum | Yes | `paragraph` \| `heading` \| `table` \| `figure` \| `list` \| `section_header` \| `caption` \| `other` — Semantic type of the content. |
| **page_refs** | list of integer | Yes | 1-based page numbers where this LDU's content originates. Non-empty. For content spanning pages, list all pages (e.g. `[5, 6]`). |
| **bounding_box** | object | Yes | Spatial provenance. Format: `{x0, top, x1, bottom}` or equivalent (points or normalized [0,1]). For multi-page LDUs, may be a list of bboxes per page or the union. Must enable "Where in the document is this?" |
| **parent_section** | string (optional) | No | Section header (or section ID) that contains this LDU. Enables section-scoped retrieval and PageIndex alignment. |
| **token_count** | integer | Yes | Approximate token count of `content` (e.g. tiktoken, or chars/4 heuristic). Used for retrieval filtering and overflow handling. |
| **content_hash** | string | Yes | Stable hash of the content (see §7). Enables provenance verification when layout shifts. |
| **relationships** | list of Relationship | No | References to other LDUs (e.g., "see Table 3" → link to table LDU). See §4.2. |

### 4.2 Relationship (cross-references)

| Field | Type | Description |
|-------|------|-------------|
| **target_ldu_id** | string | ID of the referenced LDU. |
| **relation_type** | enum | `references_table` \| `references_figure` \| `references_section` \| `references_clause` \| `other` — Semantic type of the reference. |
| **anchor_text** | string (optional) | The referring text (e.g. "Table 3", "Section 4.2"). |

Cross-references are resolved when the Chunking Engine detects patterns like "see Table 3", "Figure 2 shows", "Section 5.1", etc. Resolution maps these to the corresponding LDU IDs and stores them in `relationships`. If resolution fails (e.g., target not found), the relationship may be omitted or stored with `target_ldu_id=null` and a note.

### 4.3 Chunk type semantics

| chunk_type | Content semantics | Example |
|------------|-------------------|---------|
| **paragraph** | Prose block; may be multiple sentences. | Body text, narrative. |
| **heading** | Section or subsection title. | "3.2 Financial Performance" |
| **table** | Structured table: header row + data rows. Never split. | Income statement, balance sheet. |
| **figure** | Figure or chart; content is caption/alt text. Caption is metadata of the figure. | "Figure 2: Revenue by region" |
| **list** | Numbered or bulleted list; kept as single LDU unless exceeds max_tokens. | Findings 1–5, bullet list. |
| **section_header** | Header used as metadata for child chunks; may also be emitted as its own LDU for retrieval. | "4. Risk Factors" |
| **caption** | Caption text; always attached to parent figure or table, not standalone. | "Table 3: Quarterly results" |
| **other** | Content that does not fit above; fallback. | Footnotes, headers, unknown. |

---

## 5. Chunking Rules ("Chunking Constitution")

The Chunking Engine enforces **five mandatory rules**. These are the "Constitution" for data quality. No LDU may violate any rule; the ChunkValidator (see §6) must reject output that breaks them.

### Rule 1: Table header + cells are atomic

**Statement:** A table cell is never split from its header row.

**Explanation:** A table is emitted as a **single LDU**. The `content` field contains the full table: headers and all data rows. If a table is large (rows × cols produces content exceeding `max_tokens`), the table may be split only at **row boundaries**—e.g., emit multiple table LDUs (Table Part 1, Table Part 2), each with its own copy of the header row. A cell must never appear without its column header in the same retrieval context. Splitting mid-row or mid-cell is **forbidden**.

**Rationale:** Financial tables, tax tables, and data reports rely on header semantics. "What is the Q3 revenue?" requires the column header "Q3" to be present with the cell value. Severing them causes hallucination.

---

### Rule 2: Figure caption is metadata of parent figure

**Statement:** A figure caption is always stored as metadata of its parent figure chunk.

**Explanation:** A figure and its caption form **one LDU** of type `figure`. The `content` field includes the caption (and optionally alt_text). The caption is not emitted as a separate LDU. If the extraction layer provides a figure with a caption, the Chunking Engine must merge them into a single LDU. The caption provides the semantic description for retrieval; the figure bbox and page provide provenance.

**Rationale:** "What does Figure 2 show?" must return the caption ("Revenue by region") with the figure reference. A standalone caption LDU would be retrieved without spatial linkage to the figure; a figure without caption would be uninterpretable.

---

### Rule 3: Numbered lists are single LDUs (unless oversized)

**Statement:** A numbered list is always kept as a single LDU unless it exceeds `max_tokens`.

**Explanation:** Consecutive list items (detected via `block_type=list_item` or numbering patterns) form **one LDU** of type `list`. The entire list is emitted as a single chunk. If the list exceeds `max_tokens`, split only at **list item boundaries**—e.g., items 1–3 in one LDU, items 4–7 in another. Each sub-list LDU must retain enough context (e.g., the section or list header) to be self-contained. Never split mid-item.

**Rationale:** "What is the third finding?" requires the full list context. Splitting mid-list loses enumeration semantics and produces wrong or incomplete answers.

---

### Rule 4: Section headers as parent metadata

**Statement:** Section headers are stored as parent metadata on all child chunks within that section.

**Explanation:** When traversing in reading order, the Chunking Engine tracks the current section header (e.g., "4. Risk Factors"). Every LDU emitted until the next section header receives `parent_section` set to that header (or its ID). This enables section-scoped retrieval: "What are the risk factors?" can filter LDUs where `parent_section` contains "Risk Factors". Section headers may also be emitted as their own LDUs (chunk_type `section_header` or `heading`) for direct retrieval of section titles.

**Rationale:** Long documents (e.g. 400-page reports) require navigation by section. Parent metadata allows PageIndex and retrieval to scope queries without embedding the full document.

---

### Rule 5: Cross-reference resolution

**Statement:** Cross-references (e.g., "see Table 3") are resolved and stored as chunk relationships.

**Explanation:** When an LDU's content contains a reference to another document element (e.g., "as shown in Table 3", "Figure 2 illustrates", "Section 5.1 provides"), the Chunking Engine must: (1) identify the target (by label, number, or ID), (2) resolve it to the corresponding LDU ID, (3) add a `Relationship` to the `relationships` list of the referring LDU. If the target cannot be resolved (e.g., "Table 3" not found), the relationship may be omitted or stored with a null target and a reason. Resolution is best-effort; failure to resolve does not block LDU emission.

**Rationale:** "What does Table 3 say?"—if the question originates from a paragraph that references Table 3, the relationship allows the retrieval layer to fetch both the referring context and the table. Semantic connections are preserved for multi-hop reasoning.

---

## 6. ChunkValidator Requirements

Before emitting LDUs, the Chunking Engine must run a **ChunkValidator** that verifies the following conditions. If any check fails, the validator must **reject** the offending LDU(s) and either: (a) correct the chunking (retry with adjusted logic), or (b) emit an error and not pass invalid output downstream. The pipeline must not produce LDUs that violate the constitution.

### 6.1 Mandatory checks

| Check | Condition | Failure action |
|-------|-----------|----------------|
| **No table split across LDUs** | No table's header row appears in one LDU and its data cells in another without the header. If a table is split into multiple LDUs (e.g., by row), each LDU must contain the header row. | Reject; fix chunking logic. |
| **Every LDU has page_refs** | `page_refs` is non-empty for every LDU. | Reject LDU; log. |
| **Every LDU has bounding_box** | `bounding_box` is non-null and valid (covers the content's spatial extent). | Reject LDU; log. |
| **Figure + caption unity** | No figure LDU exists without its caption when caption was present in ExtractedDocument; no standalone caption LDU for a figure that has a caption. | Reject; merge figure and caption. |
| **List integrity** | No list LDU is split mid-item (e.g., item 3.5 or a partial sentence). | Reject; re-chunk at list boundaries. |
| **content_hash present** | Every LDU has a non-empty `content_hash`. | Reject LDU; log. |
| **token_count within limits** | No LDU exceeds `max_tokens` unless it is a single structural unit (e.g., one long paragraph) that cannot be split further without violating rules. Oversized single units are allowed but should be logged. | Log; optionally flag for review. |

### 6.2 Invariants (post-conditions)

After validation, the following must hold for the emitted `List[LDU]`:

- All LDUs have unique `id` within the document.
- LDUs are in reading order (consistent with ExtractedDocument's `reading_order`).
- No rule from §5 is violated.
- Every LDU can be traced back to at least one element in ExtractedDocument (text_block, table, or figure).

---

## 7. content_hash Requirements

The `content_hash` is a stable fingerprint of the LDU's content, used for provenance verification and deduplication. It mirrors Week 1's spatial hashing pattern: "addressing that remains valid even when content moves."

### 7.1 Required properties

| Property | Requirement |
|----------|-------------|
| **Deterministic** | Same content must always produce the same hash. No randomness. |
| **Stable across minor layout changes** | Small formatting changes (e.g., whitespace normalization, font changes, minor bbox shifts) must **not** change the hash. The hash should be computed over **normalized content** (e.g., trimmed, whitespace-collapsed text) rather than raw bytes. |
| **Collision risk acceptable** | Perfect collision resistance is not required. The hash is used for: (1) quick equality checks between LDUs, (2) provenance verification ("does this citation still point to the same content?"), (3) deduplication within a corpus. A 64-bit or 128-bit hash (e.g., xxHash, SHA-256 truncated) is sufficient. MD5 is acceptable for non-security use. |
| **Content-scoped** | The hash is computed over the LDU's `content` (and optionally `chunk_type` if needed to distinguish same-text different-type). It does **not** include `page_refs` or `bounding_box`—those can change when the document is reflowed or re-paginated; the hash should remain valid. |
| **Provenance linkage** | When a query answer cites an LDU, the citation includes `content_hash`. A verification step can re-fetch the LDU and confirm the hash matches. If the document is updated and the content changes, the hash will differ—signaling that the citation may be stale. |

### 7.2 Normalization (recommended)

Before hashing, normalize the content to reduce false negatives from trivial differences:

- Trim leading/trailing whitespace.
- Collapse multiple spaces/newlines to one space (or a standard form).
- Optionally: lowercase for case-insensitive comparison, or preserve case for exact match—configurable.
- For tables: use a canonical serialization (e.g., tab-separated or JSON with sorted keys) so cell order and formatting do not affect the hash.

---

## 8. Performance & Limits

### 8.1 Expected scale

| Metric | Expected range | Notes |
|--------|----------------|-------|
| **LDUs per document** | 10–10,000+ | Depends on document length and structure. A 400-page report with many tables and sections may produce thousands of LDUs. |
| **Max LDUs per document (recommended)** | Configurable (e.g., 50,000) | Very large documents (e.g., 1000+ pages, hundreds of tables) may exceed practical limits. The Chunking Engine should support a configurable cap. |
| **Max tokens per LDU** | Configurable (e.g., 512–2048) | Typical RAG chunk sizes. Oversized structural units (e.g., one giant table) may exceed this; they are allowed but logged. |

### 8.2 Handling very large documents

| Scenario | Behavior |
|----------|----------|
| **Document exceeds LDU cap** | Emit LDUs up to the cap in reading order; log that the cap was hit and how many elements were not chunked. Optionally emit a partial result with a `truncated=true` flag. Downstream (PageIndex, vector store) must handle partial documents. |
| **Single table exceeds max_tokens** | Split at row boundaries only. Each sub-table LDU gets the full header row. Emit multiple table LDUs. |
| **Single list exceeds max_tokens** | Split at list item boundaries. Each sub-list LDU retains parent_section context. |
| **Memory pressure** | Process ExtractedDocument in a streaming or batched fashion if needed. Emit LDUs incrementally rather than holding the full list in memory. Implementation choice. |

### 8.3 Non-functional targets

- **Latency:** Chunking should complete in seconds to low tens of seconds per document for typical sizes (e.g., &lt; 200 pages). No LLM call is required for chunking; it is CPU-bound.
- **Configurability:** `max_tokens`, `max_ldus_per_document`, and chunking rule parameters (e.g., list detection patterns) must be in configuration (extraction_rules.yaml or chunking_rules.yaml). No hardcoded limits (constitution: config-over-code).

---

## 9. Edge Cases & Failure Modes

### 9.1 Noisy OCR tables

**Scenario:** Table extraction from scanned/OCR documents produces malformed structure: merged cells, wrong column boundaries, missing headers, or garbled text.

**Behavior:**

- **Best effort:** Emit table LDUs with the extracted structure. Do not silently drop tables. Mark low-confidence tables with an optional `confidence` or `extraction_quality` flag if available from the extraction layer.
- **Fallback:** If table structure is unusable (e.g., no rows, no headers), emit the table region as a single LDU of type `paragraph` or `other` with the raw text, preserving page and bbox. Log the downgrade.
- **ChunkValidator:** Still enforce Rule 1—no split of header from cells. If the "header" is ambiguous, treat the first row as header. Do not split mid-row.

### 9.2 Missing reading order

**Scenario:** ExtractedDocument has empty or inconsistent `reading_order`.

**Behavior:**

- **Fallback order:** Derive reading order from spatial layout (top-to-bottom, left-to-right by bbox) or from element order in `text_blocks`, `tables`, `figures`. Document the fallback in logs.
- **Validation:** ChunkValidator should warn if reading order was inferred rather than explicit.

### 9.3 Unresolved cross-references

**Scenario:** "See Table 3" but no table with that label exists in the document (extraction missed it, or it's in an appendix).

**Behavior:**

- Emit the referring LDU without the relationship, or with `target_ldu_id=null` and `relation_type=unresolved`. Do not block LDU emission.
- Log unresolved references for manual review or extraction improvement.

### 9.4 Empty or near-empty ExtractedDocument

**Scenario:** Extraction failed or produced no content (e.g., all pages image-only with no OCR).

**Behavior:**

- Emit empty `List[LDU]` and log. Downstream stages (PageIndex, vector store) must handle empty LDU lists—e.g., skip indexing, or create a minimal placeholder.
- Do not emit LDUs with empty `content`; ChunkValidator should reject them.

### 9.5 Conflicting structure (figure vs. table)

**Scenario:** Extraction classifies a region as both figure and table, or the same bbox appears in multiple elements.

**Behavior:**

- Deduplicate by bbox overlap or ID. Prefer the more specific type (table over figure for grid-like content). Log conflicts.
- Ensure no duplicate LDUs for the same spatial region.

### 9.6 Degradation principle

When the Chunking Engine cannot confidently form clean LDUs (e.g., severely noisy OCR, corrupted structure), it must **fail explicitly** rather than emit low-quality output. Options:

- Emit a reduced set of LDUs with a `degraded=true` or `low_confidence` flag on the document or on individual LDUs.
- Emit an error and no LDUs, with a clear reason (e.g., `extraction_quality_below_threshold`).
- Log the failure mode for triage and extraction tuning.

The pipeline must not produce LDUs that would cause "garbage in, hallucination out" downstream. Graceful degradation means: log, flag, or fail with a clear signal—not silently pass bad data.

---

## 10. Open Questions

- **Exact max_tokens default:** 512 vs. 1024 vs. 2048—to be set in config during Phase 0/1 based on embedding model and retrieval behavior.
- **Table serialization format:** Markdown vs. JSON vs. tab-separated for table `content`—affects content_hash normalization and LLM consumption. Recommend configurable.
- **Section detection source:** Whether `parent_section` is derived from ExtractedDocument headings only, or from a separate section-detection pass (e.g., PageIndex builder). May be iterative.
- **Relationship resolution scope:** How far to go in resolving "above", "below", "preceding section"—strict label matching vs. heuristics. Best-effort is required; exact scope is implementation choice.

---

**Version:** 1.0  
**Spec status:** Ready for implementation; implementation-agnostic but sufficient for ChunkingEngine implementation.
