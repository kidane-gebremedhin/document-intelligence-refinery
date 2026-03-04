# Phase 3: Semantic Chunking Engine & PageIndex Builder — Tasks

**Source plan:** [plans/phase-3-chunking-pageindex.plan.md](../plans/phase-3-chunking-pageindex.plan.md)  
**Specs:** [04 – Semantic Chunking & LDUs](../specs/04-semantic-chunking-and-ldu-spec.md), [05 – PageIndex Builder](../specs/05-pageindex-builder-spec.md)  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§5 LDU, §6 PageIndex).

---

## P3-T001 — LDU Pydantic model and content_hash generation

**Description:** Define the **LDU** Pydantic model per [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §5 and [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §4. Fields: id, document_id, content/text, chunk_type/content_type, page_refs, bounding_box/bounding_boxes, parent_section_id (optional), token_count, content_hash, relationships (optional). Align spec 04 and spec 07 naming (e.g. content vs text) in one implementation. Implement **content_hash** generation: normalize content (trim, collapse whitespace; for tables use canonical serialization), then hash (e.g. xxHash or SHA-256 truncated). Hash must be deterministic, content-scoped (no page_refs or bbox), and stable under minor layout changes. Add validators so page_refs is non-empty and bounding_box is non-null.

**Files:**
- `src/models/` — LDU, LDUContentType (or chunk_type enum), Relationship if needed
- [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §4, §7, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §5

**Acceptance criteria:**
- LDU model instantiates with required fields; serialization to JSON round-trips.
- A validator or test rejects LDU when page_refs is empty or bounding_box is null.
- Unit test: same normalized content hashed twice yields the same content_hash; different content yields different hash.
- Unit test: whitespace-normalized content (e.g. extra spaces collapsed) yields the same hash as the original content after normalization.

---

## P3-T002 — ChunkingEngine: create LDUs from ExtractedDocument (rules 1–4)

**Description:** Implement **ChunkingEngine** that consumes an **ExtractedDocument** and produces a **list of LDUs** in reading order. Traverse ExtractedDocument in **reading_order** (or by page + position). For each element (text_block, table, figure): (1) **Rule 1** — Emit tables as one LDU (or split by row only, each part with header); never split header from cells. (2) **Rule 2** — Emit each figure with its caption in a single LDU of type figure; no standalone caption LDU. (3) **Rule 3** — Consecutive list items → one LDU of type list; if list exceeds max_tokens, split only at list item boundaries, each sub-list with context (e.g. parent_section). (4) **Rule 4** — Track current section header from heading/section_header blocks; set parent_section on every LDU until the next header; optionally emit section headers as their own LDUs. Assign id, document_id, page_refs, bounding_box, token_count (e.g. chars/4 or tiktoken), content_hash for each LDU. Load max_tokens and any rule parameters from config.

**Files:**
- `src/agents/chunker.py` or `src/chunking/` — ChunkingEngine
- Config (e.g. chunking_rules.yaml, extraction_rules.yaml) — max_tokens, max_ldus_per_document
- [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §2, §5 (rules 1–4), [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §5

**Acceptance criteria:**
- Given a valid ExtractedDocument (fixture or from extraction), ChunkingEngine produces a list of LDUs in reading order.
- Every LDU has id, content, chunk_type, page_refs, bounding_box, token_count, content_hash; table LDUs contain header and cells (or header in each row-split part); figure LDUs include caption when present; list LDUs are not split mid-item.
- At least one test or run on an ExtractedDocument with a table produces one or more table LDUs with header row present in each.
- At least one test or run on an ExtractedDocument with a figure with caption produces one figure LDU containing the caption.

---

## P3-T003 — ChunkingEngine: cross-reference resolution (rule 5) and token limits

**Description:** Add **Rule 5** to ChunkingEngine: when an LDU’s content contains references to other elements (e.g. “see Table 3”, “Figure 2 shows”, “Section 5.1”), resolve the target to an LDU id (by label, number, or id) and add a **Relationship** (target_ldu_id, relation_type, optional anchor_text) to the referring LDU. Best-effort; if target is not found, omit the relationship or store with null target and log. Do not block LDU emission. Also enforce **max_tokens** and **max_ldus_per_document**: when a list or paragraph exceeds max_tokens, split only at allowed boundaries (list item, paragraph); when total LDUs would exceed cap, stop and log (or emit partial with flag). All limits from config.

**Files:**
- ChunkingEngine (same as P3-T002), config
- [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §5 (rule 5), §8

**Acceptance criteria:**
- Unit test or run: content containing “see Table 3” (and a table with that label) produces an LDU with a relationship pointing to the table LDU id.
- When target is missing (e.g. “Table 99” not in document), the referring LDU is still emitted; relationship may be absent or null; no crash.
- When a list exceeds max_tokens, ChunkingEngine splits at list item boundaries only; each sub-list LDU has token_count ≤ max_tokens (or logged as oversized). Changing max_tokens in config changes split behavior in a test.

---

## P3-T004 — ChunkValidator implementation and unit tests (broken table, split list)

**Description:** Implement **ChunkValidator** that runs before emitting the final list of LDUs. Checks: (1) **No table split** — No table has header in one LDU and data cells in another without the header; if split by row, each part has header. (2) **Every LDU has page_refs** (non-empty). (3) **Every LDU has bounding_box** (non-null, valid). (4) **Figure + caption unity** — No figure LDU missing caption when extraction had one; no standalone caption LDU for a figure that has a caption. (5) **List integrity** — No list LDU split mid-item. (6) **content_hash present** — Every LDU has non-empty content_hash. (7) **token_count within limits** — Log or flag when an LDU exceeds max_tokens (oversized structural units allowed but logged). On failure: reject the offending LDU(s) and return a validation error (or correct and retry); do not pass invalid output downstream. Add **unit tests**: (a) Feed a list of LDUs where one LDU is a table header only and another is the same table’s data rows only (no header in second). Assert ChunkValidator rejects or fails. (b) Feed a list where a “list” LDU is clearly split mid-item (e.g. half of item 3 in one LDU, half in another). Assert ChunkValidator rejects or fails.

**Files:**
- `src/chunking/` or `src/agents/` — ChunkValidator
- Test module (e.g. `tests/test_chunk_validator.py`)
- [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §6, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §5

**Acceptance criteria:**
- ChunkValidator accepts a valid list of LDUs (all checks pass) and returns success.
- Unit test: list with “broken table” (header in one LDU, cells in another without header) → validator rejects or returns failure.
- Unit test: list with “split list” (mid-item split) → validator rejects or returns failure.
- Unit test: list with an LDU missing page_refs or content_hash → validator rejects or returns failure.

---

## P3-T005 — PageIndex build: section identification, tree, ldu_ids, persist JSON

**Description:** Implement **PageIndex builder** that consumes a list of **LDUs** (and document_id, page_count) and produces a **PageIndex tree**. **Section identification:** Use LDUs with chunk_type in `heading`, `section_header` as section titles; numbering patterns (e.g. "1.", "1.1") drive hierarchy; page_start from heading’s page_refs, page_end from last page before next sibling heading. Fallback when no headings: flat structure (e.g. one section per page) or root-only (single section spanning document). Build tree: root (page_start=1, page_end=page_count), child_sections in document order. **Mapping sections to LDUs:** For each section, set **ldu_ids** to the list of LDU ids whose parent_section matches the section or whose page_refs fall within [page_start, page_end]. Populate **key_entities** (e.g. from NER or keywords on section LDU content; optional) and **data_types_present** (from chunk_type of section LDUs: tables, figures, lists). Persist PageIndex to **`.refinery/pageindex/{document_id}.json`** (or config path). Schema per [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §3 and [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §6.

**Files:**
- `src/agents/indexer.py` or `src/pageindex/` — PageIndex builder
- Config (numbering regex, min section length, no-heading behavior)
- [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §3–4, §8, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §6

**Acceptance criteria:**
- Given a list of LDUs (with at least one heading/section_header), the builder produces a tree with root and at least one child section; each section has title, page_start, page_end, child_sections, ldu_ids (or equivalent).
- page_start ≤ page_end for every section; child section page range within parent.
- After build, a file exists at `.refinery/pageindex/{document_id}.json`; JSON contains document_id, page_count, root (or root_sections), and sections with title, page_start, page_end; loading and re-serializing yields equivalent structure.
- When LDUs have no headings, builder produces at least root-only or flat sections (no crash).

---

## P3-T006 — PageIndex section summaries (LLM)

**Description:** Add **section summaries** to the PageIndex builder. For each section node, generate a **summary** (2–3 sentences) from section title + concatenated content of the section’s LDUs (truncated if needed). Use a fast, cheap LLM (e.g. Gemini Flash, GPT-4o-mini) with a short prompt; model and prompt are configurable. On API failure or timeout, leave summary null and log; do not fail the whole build. Summaries must capture main topic and, when present, key findings or data types (tables, figures).

**Files:**
- PageIndex builder (same as P3-T005), optional summarization module
- Config (model, prompt template, enable/disable)
- [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §5

**Acceptance criteria:**
- When summarization is disabled or not implemented, PageIndex builds successfully with summary null for sections; no crash.
- When summarization is enabled and succeeds for at least one section, that section has a non-empty summary (2–3 sentences). Optional test: summary mentions section topic or data types.
- When summarization fails (e.g. mock API error), section has summary null and build completes; error is logged.

---

## P3-T007 — PageIndex query (topic → top-N sections) and retrieval narrowing demo

**Description:** Implement **PageIndex query**: input topic string (and optional document_id, top_n). Traverse the PageIndex tree; **score** each section by relevance to the topic using title, summary (if present), key_entities, data_types_present (e.g. keyword overlap or embedding similarity). Return the **top-N** sections (e.g. top 3) with id, title, page_start, page_end, summary, ldu_ids. Provide a **retrieval narrowing** step: given the top-N sections, return the set of LDU ids (or filter a list of LDUs by those sections’ ldu_ids or page range). **Demonstration:** A script or test that (1) loads a PageIndex from JSON, (2) runs the query with a topic (e.g. “risk factors” or “capital expenditure”), (3) gets top-N sections with ldu_ids, (4) verifies that filtering LDUs by those sections yields a non-empty, consistent set (e.g. all filtered LDUs have parent_section or page_refs within the selected sections).

**Files:**
- PageIndex query module (e.g. in indexer or `src/pageindex/query.py`)
- Demo script or test
- [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §7, [plans/phase-3-chunking-pageindex.plan.md](../plans/phase-3-chunking-pageindex.plan.md) §5

**Acceptance criteria:**
- PageIndex query with a topic string returns a list of sections (e.g. top 3), each with id, title, page_start, page_end, ldu_ids (or equivalent).
- Demo or test: (1) query PageIndex with topic, (2) get top-N sections, (3) filter LDUs by those sections (by ldu_ids or page range), (4) assert filtered list is non-empty and every LDU belongs to a returned section (by parent_section or page_refs).
- Optional: for a section-specific query (e.g. “risk factors”), the top-N sections include the section that contains risk factors (manual or fixture-based check).

---

## P3-T008 — Vector store ingestion of LDUs

**Description:** Implement **ingestion** of LDUs into a **vector store** (ChromaDB) so that semantic search can be run over the corpus. For each LDU: compute an embedding from its content (or text); store with metadata that includes document_id, ldu_id, page_refs, parent_section (or section id) so that retrieval can be filtered by document or by PageIndex-narrowed section. Support adding LDUs for one or many documents; ensure document_id (and optionally section/source) is queryable as metadata filter. Per Refinery Guide, use a local, free-tier-friendly store (e.g. ChromaDB or FAISS). Implementation may be minimal (e.g. in-memory or file-based) as long as “add LDUs” and “search by embedding with optional filter” are supported for the demo.

**Files:**
- `src/vector_store/` or equivalent — ingestion and search interface
- [plans/phase-3-chunking-pageindex.plan.md](../plans/phase-3-chunking-pageindex.plan.md) (vector store), [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §7.3

**Acceptance criteria:**
- After ingesting a list of LDUs, the vector store returns a non-empty result for at least one query (e.g. a phrase from an LDU’s content).
- Metadata (document_id, ldu_id, and optionally parent_section or page_refs) is stored and can be used to filter search (e.g. “only LDUs in this document” or “only LDUs in these section ids”).
- A test or script: ingest N LDUs, run a search with a filter (e.g. document_id), assert results are limited to that document.

---

## P3-T009 — Config and acceptance artifacts (LDU schema, PageIndex JSON, demo)

**Description:** Ensure **config** holds max_tokens, max_ldus_per_document, and chunking/section rules (e.g. list detection, numbering regex, no-heading behavior) per [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §8.3 and plan §6.5. No hardcoded magic numbers. Produce **acceptance artifacts**: (1) Run ChunkingEngine on at least one ExtractedDocument (from fixture or Stage 2) and confirm every LDU has id, content, chunk_type, page_refs, bounding_box, token_count, content_hash, and parent_section where applicable; optionally assert content_hash is deterministic (same content → same hash). (2) Run PageIndex builder on the resulting LDUs and confirm a PageIndex JSON exists at `.refinery/pageindex/{document_id}.json` with valid structure (root, sections, page ranges). (3) Run the PageIndex query with a topic and the retrieval narrowing step; document or assert that the candidate LDU set is restricted to the top-N sections. Changing a config value (e.g. max_tokens) and re-running chunking yields different behavior where applicable (e.g. more or fewer LDUs for a long list).

**Files:**
- Config file (chunking_rules.yaml or extraction_rules.yaml)
- Test or script that produces the acceptance artifacts
- [specs/04-semantic-chunking-and-ldu-spec.md](../specs/04-semantic-chunking-and-ldu-spec.md) §8, [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §8, [plans/phase-3-chunking-pageindex.plan.md](../plans/phase-3-chunking-pageindex.plan.md) §6

**Acceptance criteria:**
- max_tokens and at least one other chunking/section parameter are in config; code reads from config (no hardcoded constants for limits).
- Acceptance run: ExtractedDocument → ChunkingEngine → List[LDU] → every LDU has required fields and content_hash; ChunkValidator passes.
- Acceptance run: List[LDU] → PageIndex build → file at `.refinery/pageindex/{document_id}.json` with root and sections; page_start ≤ page_end, within [1, page_count].
- Acceptance run: PageIndex query with topic → top-N sections → filter LDUs by those sections → candidate set is non-empty and consistent (e.g. all from returned sections).
- Changing max_tokens in config and re-running chunking changes the number or shape of LDUs for a document that has a long list or paragraph (test or manual run).

---

## Phase 3 completion

When P3-T001 through P3-T009 are complete and their acceptance criteria met, Phase 3 acceptance checks in the plan (§6) are satisfied: LDU schema and content_hash invariants, five chunking rules and ChunkValidator (with tests for broken table and split list), PageIndex build with section identification and ldu_ids, optional summaries, PageIndex JSON on disk, PageIndex query and retrieval narrowing demo, optional vector store ingestion, and config-driven behavior with documented acceptance artifacts.
