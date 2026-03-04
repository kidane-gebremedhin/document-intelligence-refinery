# Phase 3: Semantic Chunking Engine & PageIndex Builder — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Specs:** [04 – Semantic Chunking & LDUs](../specs/04-semantic-chunking-and-ldu-spec.md), [05 – PageIndex Builder](../specs/05-pageindex-builder-spec.md).  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§5 LDU, §6 PageIndex).  
**Target:** Phase 3 — Transform raw extraction into RAG-ready LDUs and build a navigable PageIndex tree.

---

## 1. Goal

**Chunking:** Create **Logical Document Units (LDUs)** that **preserve document structure** so retrieval and RAG do not sever tables, figures, lists, or section context. The Chunking Engine consumes ExtractedDocument (from Stage 2), traverses in reading order, and emits a list of LDUs that satisfy the five chunking rules. No LDU may violate the rules; a ChunkValidator enforces this before output is passed downstream.

**PageIndex:** Build a **PageIndex tree** per document—a hierarchical navigation structure (sections with title, page range, summaries, key entities, data types) so the retrieval agent can **narrow** the search space before vector search. Each section maps to a set of LDUs; topic-based traversal returns the top-N relevant sections, then retrieval is restricted to those sections’ LDUs.

Together, Phase 3 delivers: (1) structure-respecting, provenance-carrying LDUs ready for embedding and retrieval; (2) a persisted PageIndex (e.g. `.refinery/pageindex/{document_id}.json`) that supports PageIndex-first retrieval; (3) optional ingestion of LDUs into a vector store (ChromaDB, FAISS, or equivalent) for later semantic search.

---

## 2. LDU Schema and content_hash Invariants

### 2.1 LDU schema (conceptual)

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

### 2.2 content_hash invariants

- **Deterministic** — Same content → same hash.
- **Stable across minor layout changes** — Normalize before hashing (trim, collapse whitespace); do not hash raw bytes so that reflow or font changes do not change the hash.
- **Content-scoped** — Hash is over the LDU’s content (and optionally chunk_type). Do not include page_refs or bounding_box so that re-pagination does not invalidate the hash.
- **Provenance linkage** — Citations in Stage 5 include content_hash; verification can re-fetch the LDU and confirm the hash matches.
- **Collision risk acceptable** — 64-bit or 128-bit hash (e.g. xxHash, SHA-256 truncated) is sufficient for equality checks and deduplication.

---

## 3. Chunking Rules (Five Rules) and ChunkValidator

### 3.1 The five chunking rules

1. **Table header + cells are atomic** — A table is one LDU (or multiple LDUs if split by row, each with its own copy of the header). No cell without its column header in the same LDU; no split mid-row or mid-cell.

2. **Figure caption is metadata of parent figure** — Figure and caption form one LDU of type figure. Caption is not a separate LDU.

3. **Numbered lists are single LDUs (unless oversized)** — Consecutive list items form one LDU of type list. If the list exceeds max_tokens, split only at list item boundaries; each sub-list LDU retains context (e.g. parent_section). Never split mid-item.

4. **Section headers as parent metadata** — While traversing in reading order, track the current section header. Every LDU emitted until the next section header gets `parent_section` set to that header. Section headers may also be emitted as their own LDUs (chunk_type heading / section_header).

5. **Cross-reference resolution** — When content references another element (e.g. “see Table 3”, “Figure 2 shows”), resolve to the target LDU id and add a relationship. Best-effort; failure to resolve does not block emission.

### 3.2 ChunkValidator

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

## 4. PageIndex

### 4.1 Section identification heuristics

- **Primary signal:** LDUs with chunk_type in `heading`, `section_header`. Their `content` is the section title; position in reading order and `page_refs` define section start. Numbering patterns (e.g. "1.", "1.1", "1.1.1") drive hierarchy: deeper numbering → deeper nesting.
- **Page boundaries:** Section `page_start` from the heading’s first page; `page_end` from the last page of content before the next sibling heading (or end of document).
- **Secondary signal (weak or missing headings):** Group consecutive LDUs by proximity (page, reading order); use `parent_section` from chunking to assign LDUs to sections; or create flat structure (e.g. one section per page or per N pages). Root-only fallback: single section spanning the whole document.
- **Heuristic rules:** Numbering hierarchy (2.1 child of 2); title-only fallback (e.g. “Executive Summary” by position); orphan content before first heading → “Front matter” or attach to root. Configurable: numbering regex, minimum section length, behavior when no headings.

### 4.2 Summaries (LLM)

- **Requirement:** Each section node must have a **summary** (2–3 sentences) that captures main topic and key findings. Summaries enable topic-based traversal (score sections by relevance to a query string).
- **LLM optional:** Phase 3 may use a fast, cheap LLM to generate summaries per section (input: section title + concatenated LDU content, truncated). If summarization is **not** implemented in Phase 3, leave `summary` null; topic traversal can fall back to **title** and **key_entities** (and optionally **data_types_present**). The plan treats LLM summarization as optional for Phase 3; when implemented, failure (API error, timeout) should leave summary null and log.
- **What summaries must capture (when used):** Main topic; key findings or data (tables, figures); 2–3 sentences; self-contained so “Does this section contain what I need?” can be answered without fetching LDUs.

### 4.3 Mapping sections to LDUs

- Each section node must have a way to **map to the LDUs** that belong to it. Per spec 05: **ldu_ids** (list of LDU ids) on each section. Population: all LDUs whose `parent_section` matches the section title (or section id), or whose `page_refs` fall within the section’s `[page_start, page_end]`, or both. This enables the retrieval layer to restrict vector search to LDUs in the top-N sections returned by the PageIndex query.
- **key_entities** and **data_types_present** are derived from the section’s LDUs: key_entities from NER or keywords on section content; data_types_present from chunk_type of LDUs in the section (tables, figures, lists, etc.).

---

## 5. Retrieval Flow: PageIndex-First Narrowing Before Vector Search

- **Flow:** Given a topic string (e.g. “capital expenditure projections for Q3”):
  1. **Query PageIndex** — Traverse the tree; score each section by relevance to the topic using title, summary (if present), key_entities, data_types_present. Return the **top-N** sections (e.g. top 3).
  2. **Restrict LDU set** — From the returned sections, collect `ldu_ids` (or filter LDUs by `parent_section` / page range). This is the **candidate set** for vector search.
  3. **Vector search** — Run semantic search (embed query, search vector store) **only over the candidate set** (or boost chunks from these sections). Return ranked LDUs.
- **Fallback:** If PageIndex returns no relevant sections (e.g. topic too generic), fall back to full-document vector search.
- **Success criteria:** PageIndex-first traversal should outperform naive vector search on section-specific queries (e.g. “What are the risk factors?” when the answer is in “Section 4: Risk Factors”). Measurement (precision with/without PageIndex) is part of Phase 3 acceptance where feasible.

---

## 6. Acceptance Checks

### 6.1 ChunkValidator catches broken tables and split lists

- **Broken table:** Construct or generate a candidate list of LDUs where one LDU contains only a table’s header row and another contains only the table’s data rows (no header). Run ChunkValidator; it must **reject** this (or the offending LDUs) and must not pass validation. Evidence: test that feeds such a list to the validator and asserts failure (or corrected output).
- **Split list:** Construct a list of LDUs where one “list” LDU is clearly split mid-item (e.g. first half of item 3 in one LDU, second half in another). Run ChunkValidator; it must **reject** or flag. Evidence: test that asserts list-integrity check fails for this input.

### 6.2 PageIndex JSON produced

- After running the PageIndex builder on at least one document that has LDUs (and ideally some headings), a **PageIndex JSON** file exists at `.refinery/pageindex/{document_id}.json` (or configured path).
- The JSON contains: document_id, page_count, root (or root_sections), and at least one section with title, page_start, page_end, child_sections (or equivalent). Valid page range: page_start ≤ page_end, within [1, page_count]. Evidence: file on disk; one manual or scripted check that the structure matches the schema (root, sections, hierarchy).

### 6.3 Basic demonstration: query narrowing sections

- **Demonstration:** Given a topic string (e.g. “risk factors” or “capital expenditure”), run the PageIndex query (traversal + scoring) and obtain the top-N (e.g. top 3) sections. Then either:
  - Show that the returned sections’ **ldu_ids** (or page ranges) are used to restrict a subsequent step (e.g. “only these LDUs would be searched”), or
  - Run a **basic** vector search restricted to LDUs in those sections and show that the retrieved chunks belong to the selected sections (e.g. by parent_section or page_refs).
- Evidence: script or test that (1) calls PageIndex query with a topic, (2) gets top-N sections with ldu_ids or page range, (3) verifies that a list of LDUs filtered by those sections is non-empty and consistent. Optional: compare retrieval result with and without PageIndex narrowing for one section-specific query.

### 6.4 LDU and content_hash

- At least one successful ChunkingEngine run produces a list of LDUs where every LDU has id, content, chunk_type, page_refs, bounding_box, token_count, content_hash, and (where applicable) parent_section. content_hash is deterministic (same content → same hash) and stable under whitespace normalization. Evidence: test or run that validates LDU schema and content_hash presence; optional test that hashes normalized content twice and gets the same value.

### 6.5 Configurability

- max_tokens, max_ldus_per_document, and chunking/section rules (e.g. list detection, numbering regex) are in configuration (e.g. extraction_rules.yaml or chunking_rules.yaml). No hardcoded magic numbers. Evidence: changing a config value (e.g. max_tokens) and re-running chunking yields different behavior where applicable (e.g. more or fewer LDUs for a long list).

---

**Version:** 1.0  
**Plan status:** Plan only; no code. Implementation follows this plan and specs 04, 05; models follow spec 07.
