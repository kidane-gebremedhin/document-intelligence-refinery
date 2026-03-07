# Phase 3: Semantic Chunking Engine & PageIndex Builder — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Specs:** [04 – Semantic Chunking & LDUs](../specs/04-semantic-chunking-and-ldu-spec.md), [05 – PageIndex Builder](../specs/05-pageindex-builder-spec.md).  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§5 LDU, §6 PageIndex).  
**Target:** Phase 3 — Transform raw extraction into RAG-ready LDUs and build a navigable PageIndex tree.

---

## 1. Goal

**Chunking:** Create **Logical Document Units (LDUs)** that **preserve document structure** so retrieval and RAG do not sever tables, figures, lists, or section context. The Chunking Engine consumes ExtractedDocument (from Stage 2), traverses in reading order, and emits a list of LDUs that satisfy the five chunking rules. No LDU may violate the rules; a ChunkValidator enforces this before output is passed downstream.

**PageIndex:** Build a **PageIndex tree** per document—a hierarchical navigation structure (sections with title, page range, summaries, key entities, data types) so the retrieval agent can **narrow** the search space before vector search. Each section maps to a set of LDUs; topic-based traversal returns the top-N relevant sections, then retrieval is restricted to those sections’ LDUs.

Together, Phase 3 delivers: (1) structure-respecting, provenance-carrying LDUs ready for embedding and retrieval; (2) a persisted PageIndex at `.refinery/pageindex/{document_id}.json` that supports PageIndex-first retrieval; (3) an integration point for vector store ingestion (call into the data layer) so LDUs can be ingested for later semantic search.

---

## 2. Implementation Layout and Artifacts

### 2.1 Chunking: `src/agents/chunker.py`

- **ChunkingEngine** — Consumes ExtractedDocument; traverses in reading order; applies the five chunking rules (spec 04 §5); emits a list of LDUs. Must assign id, document_id, content, chunk_type, page_refs, bounding_boxes, parent_section, token_count, content_hash, relationships. Load max_tokens and limits from config.
- **ChunkValidator** — Runs before output is passed downstream. Enforces the five rules as hard constraints (spec 04 §6): no table split without header in each part; every LDU has page_refs, bounding_boxes, content_hash; figure+caption unity; list integrity (no mid-item split); optional parent_section and token_count checks. On failure returns a validation result with error codes (e.g. TABLE_HEADER_CELLS_SPLIT, LIST_MID_ITEM_SPLIT); pipeline must not pass invalid LDUs to Stage 4.
- **Entry point** — The module (or package under `src/chunking/`) is the single place for ChunkingEngine + ChunkValidator; spec 01 §9 names `src/agents/chunker.py` as the deliverable entry.

### 2.2 PageIndex: `src/agents/indexer.py`

- **PageIndex builder** — Consumes list of LDUs and document_id, page_count; runs section identification heuristics (spec 05 §4, §4.5); builds the Section tree with title, page_start, page_end, child_sections, key_entities, data_types_present, ldu_ids; optionally runs **LLM summarization** per section (2–3 sentences). Per spec 05 §5: fast/cheap LLM, configurable; on failure leave summary null and log.
- **Artifacts** — Writes **`.refinery/pageindex/{document_id}.json`** for each document (or configured base path). JSON must contain document_id, page_count, root (Section tree), and optionally built_at. Round-trip load/save must preserve structure (spec 05 §8).
- **Entry point** — The module (or package under `src/pageindex/`) is the single place for the PageIndex builder; spec 01 §9 names `src/agents/indexer.py` as the deliverable entry.

### 2.3 Vector ingestion integration point

- **Requirement:** Phase 3 does not mandate implementing the full vector store (ChromaDB) inside the chunking/indexer code. It **does** require an **integration point**: after LDUs are produced and (optionally) after PageIndex is built, the pipeline can **call into the data layer** to ingest LDUs (e.g. embed and add to ChromaDB). The data layer interface is defined in spec 08; the indexer or a small orchestration step invokes that interface (e.g. “ingest these LDUs”) so that Phase 4 query agent can run semantic_search over the same corpus. Where this call lives (indexer vs. separate script vs. pipeline runner) is implementation-defined; the plan requires that such a call exists and is documented.

### 2.4 Artifacts summary

| Artifact | Path | Producer |
|----------|------|----------|
| PageIndex JSON per document | `.refinery/pageindex/{document_id}.json` | Indexer (src/agents/indexer.py) |
| LDUs (in-memory or persisted) | Implementation-defined | Chunker (src/agents/chunker.py) |
| Vector store (optional in P3) | `.refinery/vector_store/` (spec 08) | Data layer, invoked after indexer |

---

## 3. LDU Schema and content_hash Invariants

### 3.1 LDU schema (conceptual)

Each LDU is a typed record. Fields (per spec 04 and spec 07 §5):

- **id** — Unique within the document; stable for provenance.
- **document_id** — Same as ExtractedDocument.
- **content** / **text** — Main payload (text, or serialized table/figure caption). Spec 04 uses `content`; spec 07 uses `text`; align in implementation.
- **chunk_type** / **content_type** — Enum: paragraph, heading, table, figure, list, section_header, caption, other (spec 04); spec 07 has LDUContentType with table_section, section_intro, footnote. Map as needed.
- **page_refs** — List of 1-based page numbers; non-empty.
- **bounding_box** / **bounding_boxes** — Spatial provenance; one bbox or list per page. Non-null.
- **parent_section** / **parent_section_id** — Section title or section node ID; optional.
- **token_count** — Approximate token count of content.
- **content_hash** — Stable hash of normalized content (see §2.2).
- **relationships** — Optional list of references to other LDUs (e.g. “see Table 3” → target_ldu_id).

**Invariants (every emitted LDU):**

- `page_refs` is non-empty.
- `bounding_box` (or equivalent) is non-null and valid.
- `content_hash` is non-empty.
- Table LDUs: header + cells together; no “half table” (header in one LDU, cells in another without header).
- Figure LDUs: caption included in the same LDU (no standalone caption LDU for a figure that has a caption).
- List LDUs: no split mid-item; split only at list item boundaries if list exceeds max_tokens.

### 3.2 content_hash invariants

- **Deterministic** — Same content → same hash.
- **Stable across minor layout changes** — Normalize before hashing (trim, collapse whitespace); do not hash raw bytes so that reflow or font changes do not change the hash.
- **Content-scoped** — Hash is over the LDU’s content (and optionally chunk_type). Do not include page_refs or bounding_box so that re-pagination does not invalidate the hash.
- **Provenance linkage** — Citations in Stage 5 include content_hash; verification can re-fetch the LDU and confirm the hash matches.
- **Collision risk acceptable** — 64-bit or 128-bit hash (e.g. xxHash, SHA-256 truncated) is sufficient for equality checks and deduplication.

---

## 4. Chunking Rules (Five Rules) and ChunkValidator

### 4.1 The five chunking rules

1. **Table header + cells are atomic** — A table is one LDU (or multiple LDUs if split by row, each with its own copy of the header). No cell without its column header in the same LDU; no split mid-row or mid-cell.

2. **Figure caption is metadata of parent figure** — Figure and caption form one LDU of type figure. Caption is not a separate LDU.

3. **Numbered lists are single LDUs (unless oversized)** — Consecutive list items form one LDU of type list. If the list exceeds max_tokens, split only at list item boundaries; each sub-list LDU retains context (e.g. parent_section). Never split mid-item.

4. **Section headers as parent metadata** — While traversing in reading order, track the current section header. Every LDU emitted until the next section header gets `parent_section` set to that header. Section headers may also be emitted as their own LDUs (chunk_type heading / section_header).

5. **Cross-reference resolution** — When content references another element (e.g. “see Table 3”, “Figure 2 shows”), resolve to the target LDU id and add a relationship. Best-effort; failure to resolve does not block emission.

### 4.2 ChunkValidator

Before emitting the final list of LDUs, run a **ChunkValidator** that checks:

- **No table split across LDUs** — No table has header in one LDU and data cells in another without the header. If a table is split by rows, each part must contain the header row.
- **Every LDU has page_refs** — Non-empty; reject and log if missing.
- **Every LDU has bounding_box** — Non-null and valid; reject and log if missing.
- **Figure + caption unity** — No figure LDU missing its caption when the extraction had one; no standalone caption LDU for a figure that has a caption.
- **List integrity** — No list LDU split mid-item (e.g. partial sentence or “item 3.5”).
- **content_hash present** — Every LDU has a non-empty content_hash; reject and log if missing.
- **token_count within limits** — No LDU exceeds max_tokens unless it is a single structural unit that cannot be split without violating rules (e.g. one long paragraph). Oversized units are allowed but logged.

If any check fails, the validator must **reject** the offending LDU(s) and either correct the chunking (retry) or emit an error and not pass invalid output downstream. The pipeline must not produce LDUs that violate the constitution.

---

## 5. PageIndex

### 5.1 Section identification heuristics

- **Primary signal:** LDUs with chunk_type in `heading`, `section_header`. Their `content` is the section title; position in reading order and `page_refs` define section start. Numbering patterns (e.g. "1.", "1.1", "1.1.1") drive hierarchy: deeper numbering → deeper nesting.
- **Page boundaries:** Section `page_start` from the heading’s first page; `page_end` from the last page of content before the next sibling heading (or end of document).
- **Secondary signal (weak or missing headings):** Group consecutive LDUs by proximity (page, reading order); use `parent_section` from chunking to assign LDUs to sections; or create flat structure (e.g. one section per page or per N pages). Root-only fallback: single section spanning the whole document.
- **Heuristic rules:** Numbering hierarchy (2.1 child of 2); title-only fallback (e.g. “Executive Summary” by position); orphan content before first heading → “Front matter” or attach to root. Configurable: numbering regex, minimum section length, behavior when no headings.

### 5.2 Summaries (LLM)

- **Requirement:** Each section node must have a **summary** (2–3 sentences) that captures main topic and key findings. Summaries enable topic-based traversal (score sections by relevance to a query string).
- **LLM optional:** Phase 3 may use a fast, cheap LLM to generate summaries per section (input: section title + concatenated LDU content, truncated). If summarization is **not** implemented in Phase 3, leave `summary` null; topic traversal can fall back to **title** and **key_entities** (and optionally **data_types_present**). The plan treats LLM summarization as optional for Phase 3; when implemented, failure (API error, timeout) should leave summary null and log.
- **What summaries must capture (when used):** Main topic; key findings or data (tables, figures); 2–3 sentences; self-contained so “Does this section contain what I need?” can be answered without fetching LDUs.

### 5.3 Mapping sections to LDUs

- Each section node must have a way to **map to the LDUs** that belong to it. Per spec 05: **ldu_ids** (list of LDU ids) on each section. Population: all LDUs whose `parent_section` matches the section title (or section id), or whose `page_refs` fall within the section’s `[page_start, page_end]`, or both. This enables the retrieval layer to restrict vector search to LDUs in the top-N sections returned by the PageIndex query.
- **key_entities** and **data_types_present** are derived from the section’s LDUs: key_entities from NER or keywords on section content; data_types_present from chunk_type of LDUs in the section (tables, figures, lists, etc.).

---

## 6. Retrieval Flow: PageIndex-First Narrowing Before Vector Search

- **Flow:** Given a topic string (e.g. “capital expenditure projections for Q3”):
  1. **Query PageIndex** — Traverse the tree; score each section by relevance to the topic using title, summary (if present), key_entities, data_types_present. Return the **top-N** sections (e.g. top 3).
  2. **Restrict LDU set** — From the returned sections, collect `ldu_ids` (or filter LDUs by `parent_section` / page range). This is the **candidate set** for vector search.
  3. **Vector search** — Run semantic search (embed query, search vector store) **only over the candidate set** (or boost chunks from these sections). Return ranked LDUs.
- **Fallback:** If PageIndex returns no relevant sections (e.g. topic too generic), fall back to full-document vector search.
- **Success criteria:** PageIndex-first traversal should outperform naive vector search on section-specific queries (e.g. “What are the risk factors?” when the answer is in “Section 4: Risk Factors”). Measurement (precision with/without PageIndex) is part of Phase 3 acceptance where feasible.

---

## 7. Acceptance Checks

### 7.1 Validator unit tests for rule violations

- **ChunkValidator** must have **unit tests** that assert failure (or corrected output) when given LDUs that violate the five chunking rules. Evidence:
  - **Broken table:** A test feeds a list where one LDU is a table header only and another is the same table’s data rows only (no header in the second). ChunkValidator must reject (or return a validation result with error code such as TABLE_HEADER_CELLS_SPLIT). Assert validation fails.
  - **Split list:** A test feeds a list where a “list” LDU is clearly split mid-item (e.g. first half of item 3 in one LDU, second half in another). ChunkValidator must reject or flag (e.g. LIST_MID_ITEM_SPLIT). Assert validation fails.
  - **Missing page_refs or content_hash:** A test feeds an LDU with empty page_refs or missing content_hash. ChunkValidator must reject (e.g. PAGE_REFS_EMPTY, CONTENT_HASH_MISSING). Assert validation fails.
- **Valid list:** A test feeds a compliant list of LDUs; ChunkValidator must accept and return success. Evidence: unit tests in the repo (e.g. `tests/test_chunk_validator.py` or equivalent).

### 7.2 PageIndex JSON generation for corpus documents

- After running the PageIndex builder on **corpus documents** (at least one document that has LDUs, and ideally some headings), a **PageIndex JSON** file must exist for each such document at **`.refinery/pageindex/{document_id}.json`** (or configured path).
- The JSON must contain: document_id, page_count, root (or root_sections), and at least one section with title, page_start, page_end, child_sections (or equivalent). Valid page range: page_start ≤ page_end, within [1, page_count]. Evidence: file on disk for each processed document; a scripted or manual check that the structure matches the schema (root, sections, hierarchy). For a small corpus (e.g. 2–3 documents), all must have a corresponding pageindex file after the index step.

### 7.3 Demo flow: PageIndex-first retrieval improves section targeting

- **Demonstration:** Show that **PageIndex-first retrieval** improves section targeting compared to naive (full-document) vector search. Evidence:
  - Run **pageindex_query(topic)** (or equivalent) with a section-specific topic (e.g. “risk factors”, “capital expenditure”, “auditor’s opinion”) and obtain the top-N (e.g. top 3) sections.
  - Restrict the candidate LDU set to those sections’ ldu_ids (or filter by page range / parent_section).
  - Run semantic search (or a simulated retrieval) **only over that candidate set** and confirm that the returned chunks belong to the selected sections (e.g. by parent_section or page_refs).
  - **Optional comparison:** For the same topic, run naive vector search over all LDUs and compare: PageIndex-first should return chunks that are more consistently from the relevant section(s); or document the improvement (e.g. “top-3 sections contain the answer; naive search ranks a chunk from another section higher”). The demo flow must be reproducible (script or test) and show that PageIndex-first retrieval improves section targeting.
- Evidence: script or test that (1) loads PageIndex and LDUs, (2) runs PageIndex query with a topic, (3) filters LDUs by returned sections, (4) asserts filtered set is non-empty and that retrieval from that set returns section-relevant chunks. Optional: side-by-side comparison with full-document search for one section-specific query.

### 7.4 LDU and content_hash

- At least one successful ChunkingEngine run produces a list of LDUs where every LDU has id, content, chunk_type, page_refs, bounding_boxes, token_count, content_hash, and (where applicable) parent_section. content_hash is deterministic (same content → same hash) and stable under whitespace normalization. Evidence: test or run that validates LDU schema and content_hash presence; optional test that hashes normalized content twice and gets the same value.

### 7.5 Configurability

- max_tokens, max_ldus_per_document, and chunking/section rules (e.g. list detection, numbering regex) are in configuration (e.g. extraction_rules.yaml or chunking_rules.yaml). No hardcoded magic numbers. Evidence: changing a config value (e.g. max_tokens) and re-running chunking yields different behavior where applicable (e.g. more or fewer LDUs for a long list).

---

**Deliverables (Refinery Guide §8):** Final repo requires **`src/agents/chunker.py`** (ChunkingEngine + ChunkValidator enforcing all 5 rules), **`src/agents/indexer.py`** (PageIndex builder + optional LLM section summaries), and an integration point for vector ingestion (call into data layer). Artifacts: **`.refinery/pageindex/{document_id}.json`** per document. See [spec 01 §9](../specs/01-document-intelligence-refinery-system.md#9-deliverables-refinery-guide-8).

**Version:** 1.0  
**Plan status:** Plan only; no code. Implementation follows this plan and specs 04, 05; models follow spec 07.
