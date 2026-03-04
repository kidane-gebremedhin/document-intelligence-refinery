# Phase 4: Query Interface Agent & Provenance Layer — Tasks

**Source plan:** [plans/phase-4-query-provenance.plan.md](../plans/phase-4-query-provenance.plan.md)  
**Specs:** [06 – Query Agent & Provenance](../specs/06-query-agent-and-provenance-spec.md), [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§7 ProvenanceChain, §8 FactRecord).

---

## P4-T001 — FactTable SQLite schema and database creation

**Description:** Define and create the **FactTable** in SQLite per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §5.1 and [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §8. Schema: `id` (integer PK, auto-increment), `document_id`, `entity`, `metric`, `value` (string or numeric), `unit` (optional), `period` (optional), `source_reference` (required — resolvable to page and ideally bbox/content_hash). Provide a **create table** migration or init script; store DB path in config (e.g. `.refinery/fact_table.db`). Ensure `source_reference` is never null (constraint or application invariant).

**Files:**
- `src/data/` or `src/fact_table/` — schema definition, DB init
- Config — fact_table path
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §5.1, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §8

**Acceptance criteria:**
- Running init creates the FactTable with the required columns; `source_reference` has a NOT NULL constraint (or equivalent).
- Unit test or script: insert a row with all fields including `source_reference`; select returns the row. Insert without `source_reference` fails (constraint or validation).
- Documented schema matches plan §4.1 and spec 06 §5.1.

---

## P4-T002 — FactTable extraction from LDUs (schema + extraction rules)

**Description:** Implement **FactTable extraction** that consumes LDUs (e.g. table and optionally narrative) and inserts rows into the FactTable per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §5.2. **Extraction rules:** Target documents by domain_hint or chunk_type (e.g. table-heavy); from each LDU extract entity, metric, value, unit, period; set **source_reference** to a string resolvable to that LDU (e.g. `page:{page},ldu:{ldu_id}` or `page:{page}` so Citation can get page and optionally bbox/content_hash). Use LLM-based extraction, rule-based table parsing, or hybrid; output must conform to FactTable schema. Config: which documents to run on, which metrics to extract, enable/disable.

**Files:**
- `src/fact_table/` or `src/agents/fact_extractor.py` — extractor
- Config — extraction scope, metrics, model/prompt if LLM
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §5.2, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §8

**Acceptance criteria:**
- Given a list of LDUs containing at least one table LDU (or narrative with a figure), the extractor inserts one or more FactTable rows with entity, metric, value, and non-empty source_reference.
- Unit test: extract from fixture LDUs; assert FactTable contains rows and each row has source_reference that includes page (and optionally ldu_id). Resolving source_reference yields a valid page number (and optionally document_id).
- Config toggle (e.g. disable extraction for a document type) prevents inserts when disabled.

---

## P4-T003 — Vector store retrieval (semantic_search)

**Description:** Implement the **semantic_search** capability used by the query agent per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.2. **Inputs:** query string, optional document_ids, optional section_constraint (page range or section ids from pageindex_navigate), optional top_k. **Behavior:** Embed the query; search the vector store (from Phase 3). If section_constraint is provided, filter results to LDUs within those sections (by metadata: parent_section, page_refs, or ldu_ids). Return ranked results with: content, document_id, ldu_id, page_refs, bounding_box, content_hash, parent_section (so each result can be turned into a Citation). Expose as a function or callable used by the agent tool layer.

**Files:**
- `src/vector_store/` or `src/retrieval/` — search API
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.2, [plans/phase-4-query-provenance.plan.md](../plans/phase-4-query-provenance.plan.md) §2.2

**Acceptance criteria:**
- Unit test: with a populated vector store (fixture or from P3-T008), semantic_search(query, top_k=3) returns up to 3 results; each result has document_id, ldu_id, page_refs (or page), bounding_box, content_hash, content.
- Unit test: semantic_search with document_ids filter returns only LDUs from those documents. With section_constraint (e.g. section ids or page range), results are restricted to LDUs in that range (test with fixture that has sections).
- Example run: query "revenue Q3 2024" returns at least one LDU when the corpus contains matching content; results are ranked by relevance.

---

## P4-T004 — PageIndex navigation tool (pageindex_navigate)

**Description:** Implement the **pageindex_navigate** tool per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.1 and plan §2.1. **Inputs:** topic (natural language), optional document_id, optional top_n (default e.g. 3). **Behavior:** Load PageIndex (from disk or cache); score sections by relevance to topic using title, summary, key_entities, data_types_present (e.g. embedding similarity or keyword overlap). Return top-N sections with id, title, page_start, page_end, summary, ldu_ids (or equivalent) so the caller can pass a section_constraint to semantic_search. No vector search inside this tool. Expose as a callable used by the agent (e.g. tool function).

**Files:**
- `src/pageindex/` or `src/agents/tools/` — pageindex_navigate implementation
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.1, [specs/05-pageindex-builder-spec.md](../specs/05-pageindex-builder-spec.md) §7

**Acceptance criteria:**
- Unit test: load a PageIndex fixture; pageindex_navigate(topic="auditor's opinion", top_n=2) returns up to 2 sections; each has id, title, page_start, page_end, ldu_ids (or list of LDU ids for that section).
- Unit test or run: with document_id set, only sections from that document are considered; returned sections have page ranges within the document.
- Example run: topic "capital expenditure projections" returns sections whose title or summary matches; output can be used as section_constraint for semantic_search (e.g. ldu_ids or page range).

---

## P4-T005 — SQLite fact query interface (structured_query)

**Description:** Implement the **structured_query** capability per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.3. **Inputs:** query (natural language or parameterized), optional document_ids. **Behavior:** Map the query to a FactTable SQL query (e.g. via templates, parameterized query, or LLM-generated SQL). Execute against the SQLite FactTable. Return rows with entity, metric, value, unit, period, **source_reference** (and document_id). Apply document_ids filter when provided. Expose as a function or callable used by the agent tool. When FactTable is empty or query returns no rows, return empty list (agent will fall back to semantic_search).

**Files:**
- `src/fact_table/` or `src/agents/tools/` — structured_query implementation
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.3, §5.1

**Acceptance criteria:**
- Unit test: with FactTable containing rows (e.g. entity="X", metric="revenue", period="Q3 2024"), structured_query("revenue Q3 2024") or equivalent returns at least one row with value, source_reference, document_id.
- Unit test: structured_query with document_ids returns only facts from those documents. When no row matches, returns empty list (no exception).
- Unit test or run: every returned row has non-empty source_reference so provenance can be built.

---

## P4-T006 — ProvenanceChain and Citation wiring (bbox + page + content_hash)

**Description:** Implement **ProvenanceChain** and **Citation** models and wiring per [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §7 and [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §4. **Models:** ProvenanceChain (e.g. answer_id, items list); Citation/ProvenanceItem with required fields: document_id, document_name, page_number, bounding_box, content_hash (for LDU-backed); optional snippet, ldu_id, chunk_type. **Wiring:** (1) **LDU → Citation:** From a retrieved LDU, build a Citation with document_id, document_name (resolve via P4-T007), page_number from page_refs, bounding_box, content_hash, optional snippet from content. (2) **FactTable row → Citation:** From a row with source_reference, resolve to at least page_number and document_id; optionally to bbox and content_hash if stored; bounding_box may be null for fact-only citations. Enforce invariants: no citation emitted with missing required fields for its source type; citations only from actually retrieved LDUs or fact rows.

**Files:**
- `src/models/` — ProvenanceChain, Citation/ProvenanceItem
- `src/agents/provenance.py` or equivalent — ldu_to_citation, fact_row_to_citation
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §4, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §7

**Acceptance criteria:**
- Unit test: given a full LDU (with document_id, page_refs, bounding_box, content_hash, content), ldu_to_citation(ldu, document_name) returns a Citation with all required fields; document_name is the provided value.
- Unit test: given a FactTable row with source_reference "page:42,ldu:ldu_01", fact_row_to_citation(row, document_name, optional LDU lookup) returns a Citation with document_id, document_name, page_number=42; bounding_box present if resolvable, else null. No citation when source_reference is missing or invalid.
- Unit test: building a ProvenanceChain from a list of Citations succeeds; serialization to JSON round-trips. Validator or test rejects Citation with missing required fields (for LDU: bbox, content_hash; for fact: page_number).

---

## P4-T007 — Document name resolution (document_id → document_name)

**Description:** Provide **document name resolution** so that every Citation can include a human-readable **document_name** (e.g. filename, report title) per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §4.2. Implement a lookup: document_id → document_name. Source may be a registry file (e.g. `.refinery/documents.json`), document metadata from triage, or filename from pipeline config. When document_id is unknown, return a fallback (e.g. document_id itself or "Unknown document") so provenance never fails for missing name; log the miss.

**Files:**
- `src/data/` or `src/agents/` — document registry or resolver
- Config or refinery artifact — where document names are stored
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §4.2

**Acceptance criteria:**
- Unit test: resolve(document_id) returns a non-empty string (e.g. filename). When document_id is in the registry, returned name matches. When document_id is unknown, returns fallback string and does not raise; optional: log or capture miss.
- Integration: provenance wiring (P4-T006) uses this resolver so every Citation has document_name set.

---

## P4-T008 — Query agent orchestration (tools + ProvenanceChain on answer)

**Description:** Implement the **Query Interface Agent** that orchestrates the three tools and returns an **answer plus ProvenanceChain** per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3.4 and plan §2.4. **Tools:** pageindex_navigate (P4-T004), semantic_search (P4-T003), structured_query (P4-T005). **Orchestration:** Based on query intent (navigational, numerical, synthesis), call one or more tools; combine results. **Provenance:** For every answer, build ProvenanceChain from cited LDUs and/or FactTable rows using P4-T006 and P4-T007. Use LangGraph or equivalent (graph with tool nodes, conditional edges). Config: top_k, top_n, timeouts, tool selection heuristics. Ensure that when context is empty (no results from any tool), the agent returns a clear "No relevant content found" (or similar) and does not invent citations.

**Files:**
- `src/agents/query_agent.py` or `src/query/` — agent graph, tool bindings, response builder
- Config — top_k, top_n, timeouts, routing
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §3, §6, [plans/phase-4-query-provenance.plan.md](../plans/phase-4-query-provenance.plan.md) §2.4

**Acceptance criteria:**
- Example Q&A run: ask a natural-language question (e.g. "What was revenue in Q3 2024?" or "What are the main risk factors?") over a corpus with LDUs (and optionally FactTable). Response includes an **answer** and a **ProvenanceChain** with at least one citation. Each citation has document_name, document_id, page_number, bounding_box, content_hash (for LDU-backed).
- Unit test or trace: for a navigational query (e.g. "Where is the auditor's opinion?"), the agent calls pageindex_navigate then semantic_search with section constraint; ProvenanceChain cites LDUs from the returned sections.
- Unit test or trace: for a numerical query with FactTable populated, agent uses structured_query and answer includes citation(s) from source_reference. When FactTable is empty or returns no match, agent falls back to semantic_search and still returns answer + ProvenanceChain from LDUs (no crash).
- Changing config (e.g. top_k) changes retrieval count where applicable.

---

## P4-T009 — Audit mode (verify claim → verified or unverifiable)

**Description:** Implement **Audit mode** per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §7 and plan §5. **Input:** claim (string), optional document_id. **Behavior:** (1) Parse the claim (entities, metric, value, period). (2) Query FactTable via structured_query and semantic_search with the claim (or reformulation). (3) Evaluate whether any retrieved content supports the claim. (4) **Output:** If supported → **verified** + ProvenanceChain with supporting citation(s). If not supported → **unverifiable** + explicit message (e.g. "The claim could not be verified. No supporting source was found."); **no citation** and no invented page/bbox. Enforce invariants: never return a citation without a supporting source; never hallucinate page or bbox; response clearly distinguished verified vs unverifiable.

**Files:**
- `src/agents/audit.py` or `src/query/audit.py` — audit mode entry, claim parsing, evaluation, response builder
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §7, §8, [plans/phase-4-query-provenance.plan.md](../plans/phase-4-query-provenance.plan.md) §5

**Acceptance criteria:**
- Unit test: audit(claim="The report states revenue was $99.9B in Q1 2099", document_id=doc_without_this) returns **unverifiable** (or equivalent status) and **no citation** (empty ProvenanceChain or explicit "unverifiable" and citation list empty). Response text states that the claim could not be verified.
- Unit test: audit(claim=<fact that exists in corpus>, document_id=doc_id) returns **verified** and ProvenanceChain with at least one citation pointing to the supporting source. Citation has valid document_id, page_number, and no invented bbox (bbox from source or null).
- Unit test: when no document is indexed or corpus is empty, audit returns unverifiable and no citation. No exception; message indicates corpus/document not indexed or no source found.

---

## P4-T010 — Config, logging, and acceptance artifacts

**Description:** Ensure **config** holds tool parameters (top_k, top_n, timeouts, FactTable path, document registry path) and optional tool-selection/routing settings per [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §9.4. Implement **query logging:** timestamp, query text, tools invoked, result count, latency for each query (and optionally per tool). Produce **acceptance artifacts:** (1) **Example Q&A with ProvenanceChain:** Run the query agent on at least one question over a document that has been through Stages 1–4; capture response and assert it includes answer + ProvenanceChain with ≥1 citation; each citation has document_name, page_number, bounding_box, content_hash (for LDU-backed). (2) **Audit unverifiable:** Run audit mode with a claim that does not exist in the corpus; assert response is unverifiable and citation list is empty (or equivalent). (3) **Audit verified:** Run audit mode with a claim that exists in the corpus; assert response is verified and ProvenanceChain is non-empty.

**Files:**
- Config file (e.g. query_agent.yaml, refinement.yaml)
- Logging in query agent and audit code
- Test or script that produces acceptance artifacts
- [specs/06-query-agent-and-provenance-spec.md](../specs/06-query-agent-and-provenance-spec.md) §9.3, §9.4, [plans/phase-4-query-provenance.plan.md](../plans/phase-4-query-provenance.plan.md) §6

**Acceptance criteria:**
- top_k, top_n, and at least one timeout are in config; code reads from config (no hardcoded values for production tuning).
- At least one query run produces a log entry with timestamp, query text, tools invoked, result count, and latency.
- Acceptance script or test: example Q&A → response has answer + ProvenanceChain with ≥1 citation; citation fields (document_name, page_number, bounding_box, content_hash for LDU) are present and non-empty where required.
- Acceptance script or test: audit with unsupported claim → unverifiable, no citation. Audit with supported claim → verified, ≥1 citation. Document or assert that audit never invents a citation when evidence is missing.

---

## Phase 4 completion

When P4-T001 through P4-T010 are complete and their acceptance criteria met, Phase 4 plan acceptance checks are satisfied: FactTable schema and extraction, vector store retrieval (semantic_search), PageIndex navigation tool (pageindex_navigate), SQLite fact queries (structured_query), ProvenanceChain wiring (bbox + page + content_hash), document name resolution, query agent orchestration with three tools and ProvenanceChain on every answer, audit mode (verified vs unverifiable, no invented citations), config and logging, and documented acceptance runs (example Q&A with citations, audit unverifiable when no evidence).
