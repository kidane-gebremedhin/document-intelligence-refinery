# Phase 3: Semantic Chunking Engine & PageIndex Builder — Tasks

**Source plan:** [plans/phase-3-chunking-pageindex.plan.md](../plans/phase-3-chunking-pageindex.plan.md)  
**Specs:** [04 – Semantic Chunking & LDUs](../specs/04-semantic-chunking-and-ldu-spec.md), [05 – PageIndex Builder](../specs/05-pageindex-builder-spec.md)  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§5 LDU, §6 PageIndex).  
**Data layer:** [08 – Data Layer](../specs/08-data-layer-spec.md) (vector store interface for ingestion hook).

---

## P3-T001 — LDU model and content_hash utilities

**Description:** Define the **LDU** Pydantic model and **content_hash** utilities. LDU fields per [spec 07 §5](specs/07-models-schemas-spec.md) and [spec 04 §4](specs/04-semantic-chunking-and-ldu-spec.md): id, document_id, content (or text; align naming), chunk_type, page_refs, bounding_boxes, parent_section (optional), token_count, content_hash, relationships (optional). Implement **content_hash** generation: normalize content (trim, collapse whitespace; for tables use canonical serialization per [spec 04 §7](specs/04-semantic-chunking-and-ldu-spec.md)), then hash (e.g. xxHash or SHA-256 truncated). Hash must be deterministic, content-scoped (no page_refs/bbox), and stable under minor layout changes. Add validators so page_refs is non-empty and bounding_boxes is non-null.

**Files to change:**
- `src/models/` (or `src/schemas/`) — LDU, LDUContentType (or chunk_type enum), Relationship; content_hash utility function or method.

**Acceptance criteria:**
- LDU model instantiates with required fields; serialization to JSON round-trips.
- Validator or test rejects LDU when page_refs is empty or bounding_boxes is null.
- Unit test: same normalized content hashed twice yields the same content_hash; different content yields different hash.
- Unit test: whitespace-normalized content yields the same hash as the original after normalization.

**Spec references:** [04 §4](specs/04-semantic-chunking-and-ldu-spec.md), [04 §7](specs/04-semantic-chunking-and-ldu-spec.md), [07 §5](specs/07-models-schemas-spec.md).

---

## P3-T002 — ChunkValidator (5 rules) and tests

**Description:** Implement **ChunkValidator** that enforces the five chunking rules as hard constraints before LDUs are passed downstream. Checks: (1) **R1** — No table split: no LDU has table data rows without header; if table split by row, each part has header ([spec 04 §5.6](specs/04-semantic-chunking-and-ldu-spec.md), error `TABLE_HEADER_CELLS_SPLIT`). (2) **R2** — Figure + caption unity: no figure LDU missing caption when extraction had one; no standalone caption LDU for a figure (`FIGURE_CAPTION_NOT_UNIFIED`). (3) **R3** — List integrity: no list LDU split mid-item (`LIST_MID_ITEM_SPLIT`). (4) **R4** — parent_section set when section headers exist (optional hard constraint, `PARENT_SECTION_MISSING`). (5) **R5** — Cross-references best-effort; no rejection. Also: every LDU has non-empty page_refs (`PAGE_REFS_EMPTY`), valid bounding_boxes (`BOUNDING_BOXES_INVALID`), non-empty content_hash (`CONTENT_HASH_MISSING`); token_count over max_tokens: log only, do not reject. On failure return validation result with error codes and offending LDU ids; do not pass invalid output downstream. Add **unit tests** for each rule violation and for valid input.

**Files to change:**
- `src/agents/chunker.py` (or `src/chunking/`) — ChunkValidator, ValidationResult, ChunkValidationError (or equivalent).
- `tests/test_chunk_validator.py` — Tests for broken table, split list, missing page_refs, missing content_hash, valid list.

**Acceptance criteria:**
- ChunkValidator accepts a valid list of LDUs and returns success.
- Test: list with “broken table” (header in one LDU, cells in another without header) → validator rejects with error code TABLE_HEADER_CELLS_SPLIT (or equivalent).
- Test: list with “split list” (mid-item split) → validator rejects with LIST_MID_ITEM_SPLIT.
- Test: LDU with empty page_refs or missing content_hash → validator rejects with PAGE_REFS_EMPTY or CONTENT_HASH_MISSING.
- Validation result includes error codes and optional ldu_ids/indices; pipeline does not pass rejected list downstream.

**Spec references:** [04 §5.6](specs/04-semantic-chunking-and-ldu-spec.md), [04 §6](specs/04-semantic-chunking-and-ldu-spec.md), [07 §5.4](specs/07-models-schemas-spec.md).

---

## P3-T003 — ChunkingEngine implementation and tests

**Description:** Implement **ChunkingEngine** that consumes **ExtractedDocument** and produces a **list of LDUs** in reading order. Apply all five rules: (1) Tables as one LDU or row-split with header in each part. (2) Figure + caption in one LDU of type figure. (3) Consecutive list items → one list LDU; if over max_tokens, split only at list item boundaries. (4) Track current section header; set parent_section on every LDU; optionally emit section headers as LDUs. (5) Resolve cross-references to target LDU id and add Relationship; best-effort. Assign id, document_id, page_refs, bounding_boxes, token_count, content_hash per LDU. Enforce max_tokens and max_ldus_per_document from config. Run **ChunkValidator** on output before returning; on validation failure retry or raise. Add tests: ExtractedDocument with table → table LDU(s) with header; with figure+caption → one figure LDU; list over max_tokens → split at item boundaries only; “see Table 3” with target → relationship present.

**Files to change:**
- `src/agents/chunker.py` — ChunkingEngine (traverse reading_order, emit LDUs, call ChunkValidator).
- Config (e.g. `chunking_rules.yaml`, `extraction_rules.yaml`) — max_tokens, max_ldus_per_document.
- `tests/test_chunker.py` (or `tests/test_chunking_engine.py`) — Fixtures and tests for rules 1–5 and token limits.

**Acceptance criteria:**
- Given valid ExtractedDocument, ChunkingEngine produces a list of LDUs in reading order; every LDU has id, content, chunk_type, page_refs, bounding_boxes, token_count, content_hash.
- Table LDUs contain header and cells (or header in each row-split part); figure LDUs include caption when present; list LDUs not split mid-item.
- At least one test: ExtractedDocument with table → table LDU(s) with header. At least one test: figure with caption → one figure LDU. At least one test: list exceeds max_tokens → split at list item boundaries only.
- Cross-reference test: “see Table 3” with Table 3 present → LDU has relationship to table LDU id; when target missing, LDU still emitted, no crash.
- Changing max_tokens in config changes split behavior (test or run).

**Spec references:** [04 §2](specs/04-semantic-chunking-and-ldu-spec.md), [04 §5](specs/04-semantic-chunking-and-ldu-spec.md), [07 §5](specs/07-models-schemas-spec.md).

---

## P3-T004 — PageIndex models and builder implementation

**Description:** Finalize **PageIndex** and **PageIndexSection** models per [spec 07 §6](specs/07-models-schemas-spec.md) and [spec 05 §3](specs/05-pageindex-builder-spec.md). Section node fields: id, title, page_start, page_end, child_sections, key_entities, summary, data_types_present, ldu_ids. Implement **PageIndex builder** in `src/agents/indexer.py`: consume list of LDUs + document_id, page_count; run section identification heuristics ([spec 05 §4, §4.5](specs/05-pageindex-builder-spec.md)) — headings/section_header LDUs, numbering patterns, page boundaries; build tree with root (page_start=1, page_end=page_count) and child_sections; assign ldu_ids per section (parent_section or page range); populate key_entities and data_types_present from section LDUs. Config: numbering regex, min section length, no-heading behavior (flat or root-only).

**Files to change:**
- `src/models/` (or `src/schemas/`) — PageIndex, PageIndexSection (spec 07 §6).
- `src/agents/indexer.py` — PageIndex builder (section identification, tree construction, ldu_ids, key_entities, data_types_present).
- Config — numbering regex, section heuristics.

**Acceptance criteria:**
- Given list of LDUs with at least one heading/section_header, builder produces a tree with root and at least one child section; each section has title, page_start, page_end, child_sections, ldu_ids.
- page_start ≤ page_end for every section; child section page range within parent.
- When LDUs have no headings, builder produces root-only or flat sections (no crash).
- key_entities and data_types_present populated from section LDUs (or stubbed); ldu_ids correctly map LDUs to sections.

**Spec references:** [05 §3](specs/05-pageindex-builder-spec.md), [05 §4](specs/05-pageindex-builder-spec.md), [05 §4.5](specs/05-pageindex-builder-spec.md), [07 §6](specs/07-models-schemas-spec.md).

---

## P3-T005 — LLM summarizer interface (stubbed) and caching

**Description:** Add **section summarization** to the PageIndex builder. Define an **LLM summarizer interface** (e.g. `summarize_section(title: str, content: str) -> str | None`) that can be implemented by a real LLM (fast/cheap model per [spec 05 §5](specs/05-pageindex-builder-spec.md)) or **stubbed** (return None or fixed string) so Phase 3 can run without an API. For each section node, call the summarizer with section title + concatenated LDU content (truncated); set `summary` to 2–3 sentences or leave null on failure or when disabled. On API failure or timeout, leave summary null and log; do not fail the build. Add **caching**: cache summaries by a stable key (e.g. document_id + section id or content hash) so repeated builds or same section do not re-call the LLM; cache may be in-memory or file-based (e.g. `.refinery/summaries/` or config path).

**Files to change:**
- `src/agents/indexer.py` (or `src/pageindex/summarizer.py`) — Summarizer interface (protocol or abstract class), stub implementation, optional LLM implementation.
- PageIndex builder — Call summarizer per section; set summary; handle null on failure.
- Cache layer (optional module or in indexer) — Key by document_id + section id (or content hash); read/write cache; config for enable/disable and path.
- Config — model, prompt template, enable/disable summarization, cache path.

**Acceptance criteria:**
- When summarization is disabled or stub returns None, PageIndex builds successfully with summary null for sections; no crash.
- When summarization is enabled and succeeds (stub or real LLM), at least one section has non-empty summary (2–3 sentences).
- When summarization fails (e.g. mock API error), section has summary null and build completes; error is logged.
- Caching: repeated build for same document/section uses cache when implemented; no duplicate LLM calls for same section (test or manual check).

**Spec references:** [05 §5](specs/05-pageindex-builder-spec.md), [plan §5.2](plans/phase-3-chunking-pageindex.plan.md).

---

## P3-T006 — PageIndex query (top-3 sections)

**Description:** Implement **pageindex_query(topic)** per [spec 05 §7](specs/05-pageindex-builder-spec.md). Input: topic (required), optional document_id, optional top_n (default **3**). Traverse the PageIndex tree; score each section by relevance to the topic using title, summary (if present), key_entities, data_types_present (e.g. keyword overlap or embedding similarity). Return the **top-N** sections (default top-3) with id, title, page_start, page_end, summary, ldu_ids, ordered by relevance descending. This result is used before vector search to narrow the candidate LDU set.

**Files to change:**
- `src/agents/indexer.py` or `src/pageindex/query.py` — pageindex_query(topic, document_id=..., top_n=3); scoring and traversal logic.
- Config — top_n default, scoring method (e.g. keyword vs embedding).

**Acceptance criteria:**
- pageindex_query(topic) returns a list of sections (default top-3), each with id, title, page_start, page_end, ldu_ids (and summary when present).
- Sections ordered by relevance score descending.
- Optional document_id filters to one document’s PageIndex when multiple are loaded.
- Test or script: load PageIndex from JSON, run pageindex_query with a topic (e.g. “risk factors”), assert top-N sections returned and ldu_ids non-empty where applicable.

**Spec references:** [05 §7](specs/05-pageindex-builder-spec.md), [plan §6](plans/phase-3-chunking-pageindex.plan.md).

---

## P3-T007 — Artifact writer to .refinery/pageindex/

**Description:** Implement **artifact writer** that persists the PageIndex to **`.refinery/pageindex/{document_id}.json`** per [spec 05 §8](specs/05-pageindex-builder-spec.md). JSON must contain document_id, page_count, root (Section tree), and optionally built_at. All section node fields required for query (title, page_start, page_end, child_sections, key_entities, summary, data_types_present, ldu_ids) must be included. Round-trip: load the file and re-serialize to equivalent structure. Path may be overridden by config (base directory); ensure directory exists before write. Invoked by the PageIndex builder after tree construction (and optional summarization).

**Files to change:**
- `src/agents/indexer.py` — write_pageindex(page_index, path_or_base_dir); path = `.refinery/pageindex/{document_id}.json` or config.
- Config — base path for .refinery or pageindex output dir.

**Acceptance criteria:**
- After build, a file exists at `.refinery/pageindex/{document_id}.json` (or configured path).
- JSON contains document_id, page_count, root (or root_sections), and section fields; valid JSON, UTF-8.
- Loading the file and re-serializing yields equivalent structure (same document_id, root, section hierarchy).
- For a small corpus (e.g. 2–3 documents), each processed document has a corresponding pageindex file after the index step.

**Spec references:** [05 §8](specs/05-pageindex-builder-spec.md), [plan §2.4](plans/phase-3-chunking-pageindex.plan.md).

---

## P3-T008 — Vector store ingestion hook (call into data layer)

**Description:** Implement an **integration point** so that after LDUs are produced (and optionally after PageIndex is built), the pipeline can **call into the data layer** to ingest LDUs for semantic search. Do not implement the full vector store inside chunking/indexer code; instead, **invoke the data layer interface** defined in [spec 08](specs/08-data-layer-spec.md) (e.g. “ingest these LDUs” — embed and add to ChromaDB). The hook may live in the indexer, a small orchestration step, or a pipeline runner; it must be documented and callable with a list of LDUs (and optionally document_id). Phase 4 query agent will run semantic_search over the same corpus; Phase 3 only requires that the call exists and is wired so ingestion can be run after chunking/indexing.

**Files to change:**
- `src/agents/indexer.py` or pipeline/orchestration module — Call data layer ingest function (e.g. `ingest_ldus(ldus: list[LDU], document_id: str)`). Document the hook and when it is invoked.
- Data layer interface (if not yet present) — Stub or real implementation of ingest_ldus per spec 08; vector store path (e.g. `.refinery/vector_store/`).

**Acceptance criteria:**
- A callable hook (function or method) exists that accepts a list of LDUs (and optionally document_id) and calls the data layer to ingest them (embed + add to vector store).
- Documentation or docstring states when the hook is invoked (e.g. after PageIndex build, or in pipeline step X).
- Test or script: after chunking, call the hook with LDUs; for Phase 3, stub ingestion is acceptable (e.g. no-op or in-memory) as long as the interface is the same; full ChromaDB ingestion may be Phase 4.
- When data layer is implemented (spec 08), the hook uses it without changing the caller’s signature.

**Spec references:** [08](specs/08-data-layer-spec.md) (vector store interface), [plan §2.3](plans/phase-3-chunking-pageindex.plan.md).

---

## Phase 3 completion

When P3-T001 through P3-T008 are complete and their acceptance criteria met, Phase 3 plan acceptance checks are satisfied: LDU schema and content_hash, ChunkValidator (5 rules) with tests, ChunkingEngine with tests, PageIndex models and builder, LLM summarizer (stubbed) with caching, pageindex_query (top-3), artifact writer to `.refinery/pageindex/`, and vector store ingestion hook calling into the data layer.
