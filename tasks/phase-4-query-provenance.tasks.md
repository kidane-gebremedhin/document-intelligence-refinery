# Phase 4: Query Interface Agent & Provenance Layer — Tasks

**Source plan:** [plans/phase-4-query-provenance.plan.md](../plans/phase-4-query-provenance.plan.md)  
**Specs:** [06 – Query Agent & Provenance](../specs/06-query-agent-and-provenance-spec.md), [08 – Data Layer](../specs/08-data-layer-spec.md)  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§7 ProvenanceChain, §7.3 QAExample, §8 FactRecord).

---

## P4-T001 — SQLite FactTable schema and Fact extractor

**Description:** Implement the **FactTable** in SQLite and the **Fact extractor** that populates it from LDUs. **Schema:** Per [spec 08 §3](specs/08-data-layer-spec.md): table `facts` with columns id (INTEGER PK AUTOINCREMENT), document_id (TEXT NOT NULL), entity, metric, value (TEXT or REAL), unit, period, category_path, source_reference (TEXT NOT NULL), source_page (optional), created_at (optional). Add indexes per spec 08 §3.3: document_id, (metric, period), (entity, metric), (document_id, source_page). Path: `.refinery/fact_table.db` (or config). **Fact extractor:** Consumes list of LDUs; per [spec 08 §2](specs/08-data-layer-spec.md) extract facts from table LDUs (and optionally narrative/list LDUs). Map to entity, metric, value, unit, period, category_path; set **source_reference** resolvable to at least document_id and page_number, ideally ldu_id/bbox/content_hash. Insert into SQLite; idempotency (e.g. upsert by source_reference) is implementation-defined. Config: which documents/metrics to extract, confidence threshold, model/prompt if LLM.

**Files to change:**
- `src/data/` or `src/fact_table/` — SQLite schema (create table + indexes), DB init, Fact extractor module
- Config — fact_table path, extraction scope, metrics, enable/disable

**Acceptance criteria:**
- Init creates `facts` table with required columns; `source_reference` NOT NULL; indexes exist. Unit test: insert row with all fields; select returns it; insert without source_reference fails.
- Given LDUs containing at least one table LDU, extractor inserts one or more rows with entity, metric, value, non-empty source_reference. Unit test: fixture LDUs → FactTable rows; each row source_reference yields valid page (and optionally document_id, ldu_id).
- Config toggle (e.g. domain_hint or disable) prevents inserts when disabled. Schema and indexes match spec 08 §3.

**Referenced specs:** [08 §2](specs/08-data-layer-spec.md), [08 §3](specs/08-data-layer-spec.md), [07 §8](specs/07-models-schemas-spec.md).

---

## P4-T002 — Vector store backend (ChromaDB): ingestion and query API

**Description:** Implement the **ChromaDB** vector store backend per [spec 08 §4](specs/08-data-layer-spec.md). **Ingestion:** Accept list of LDUs; compute embedding from LDU content; store in ChromaDB with metadata document_id, ldu_id, page_refs (or first page), bounding_boxes (or first bbox), parent_section, content_hash, chunk_type. Use ldu_id as document id for idempotent upsert. Path: `.refinery/vector_store/` (or config). **Query API:** **Search** — input: query_text, top_k, optional document_ids, optional section_constraint (ldu_ids or page range); embed query; search collection; filter by metadata when provided; return list of results with content, document_id, ldu_id, page_refs, bounding_boxes, content_hash, parent_section so each hit can be turned into a Citation. Expose ingest_ldus(ldus) and search(query_text, top_k, document_ids=..., section_constraint=...) as the data layer interface used by semantic_search tool. Config: embedding model, persist path, collection name.

**Files to change:**
- `src/data/` or `src/vector_store/` — ChromaDB client, ingest_ldus, search (query API)
- Config — vector_store path, embedding model, collection name, top_k default

**Acceptance criteria:**
- After ingest_ldus(ldus), search with a phrase from an LDU returns that LDU (or equivalent); each result has document_id, ldu_id, page_refs, bounding_boxes (or first bbox), content_hash, content.
- Search with document_ids filter returns only LDUs from those documents. Search with section_constraint (e.g. ldu_ids) returns only LDUs in that set. Unit tests with fixture or small corpus.
- Metadata stored supports building Citation (document_id, page_number, bbox, content_hash). Re-ingest with same ldu_id updates (no duplicate entries). Path and embedding model from config.

**Referenced specs:** [08 §4](specs/08-data-layer-spec.md), [06 §3.2](specs/06-query-agent-and-provenance-spec.md).

---

## P4-T003 — ProvenanceChain creation helpers (bbox + page + content_hash required)

**Description:** Implement **ProvenanceChain** and **ProvenanceItem (Citation)** models per [spec 07 §7](specs/07-models-schemas-spec.md) and [spec 06 §4](specs/06-query-agent-and-provenance-spec.md). **Models:** ProvenanceItem with required fields document_id, document_name, page_number, bbox (required for LDU-backed; may be null for FactTable-only when not stored), content_hash (required for LDU-backed; optional for FactTable); optional snippet, ldu_id. ProvenanceChain: answer_id, items (list of ProvenanceItem), optional verification_status. **Helpers:** (1) **From LDU:** `ldu_to_citation(ldu, document_name)` — build Citation with document_id, document_name (from resolver), page_number (first of page_refs), bbox (first of bounding_boxes), content_hash, optional snippet; require all LDU-backed fields. (2) **From FactTable row:** `fact_row_to_citation(row, document_name, ...)` — resolve source_reference to at least page_number, document_id; optionally bbox/content_hash if encoded; bbox may be null. (3) **Document name resolution:** document_id → document_name (registry or fallback). Invariants: no citation without required fields for source type; citations only from actual retrieval results (no invented page/bbox).

**Files to change:**
- `src/models/` — ProvenanceChain, ProvenanceItem (Citation)
- `src/agents/provenance.py` or `src/provenance/` — ldu_to_citation, fact_row_to_citation, document_id_to_name resolver
- Config or artifact — document registry path (e.g. document_id → name)

**Acceptance criteria:**
- Unit test: LDU with full fields → ldu_to_citation yields Citation with document_name, document_id, page_number, bbox, content_hash; validator rejects Citation missing bbox or content_hash for LDU source.
- Unit test: FactTable row with source_reference "page:42,ldu:ldu_01" → fact_row_to_citation yields Citation with page_number=42, document_id; bbox present if resolvable else null. No citation when source_reference missing or invalid.
- document_id → document_name: known id returns name; unknown returns fallback (no raise). ProvenanceChain from list of Citations serializes to JSON and round-trips.

**Referenced specs:** [06 §4](specs/06-query-agent-and-provenance-spec.md), [07 §7.1](specs/07-models-schemas-spec.md), [07 §7.2](specs/07-models-schemas-spec.md), [08 §6.2](specs/08-data-layer-spec.md).

---

## P4-T004 — Audit Mode: claim verification (verified / unverifiable)

**Description:** Implement **Audit Mode** per [spec 06 §7](specs/06-query-agent-and-provenance-spec.md) and [spec 08 §6](specs/08-data-layer-spec.md). **Input:** claim (string), optional document_id. **Flow:** (1) Parse claim (entity, metric, value, period). (2) structured_query(claim) and semantic_search(claim or reformulation). (3) Build provenance items **only** from returned fact rows and LDUs (spec 08 §6.2). (4) Evaluate: does any fact row or LDU content support the claim? (value/metric/period match or semantic support). (5) **Output:** If supported → **verified**, ProvenanceChain with ≥1 citation (from supporting rows/LDUs), verification_status = verified. If not supported → **unverifiable**, ProvenanceChain with **empty** items, verification_status = unverifiable, response text e.g. "The claim could not be verified. No supporting source was found." **Invariants:** Never return a citation when no source supports the claim; never invent page/bbox; unverifiable ⇒ empty citation list; verified ⇒ non-empty citation list.

**Files to change:**
- `src/agents/audit.py` or `src/query/audit.py` — audit entry, claim parsing, call structured_query + semantic_search, evaluation, response + ProvenanceChain builder
- Integration with provenance helpers (P4-T003) and data layer (P4-T001, P4-T002)

**Acceptance criteria:**
- Unit test: audit(claim="The report states revenue was $99.9B in Q1 2099", document_id=doc_without_this) → verification_status unverifiable, citation list empty, response text states claim could not be verified. No citation invented.
- Unit test: audit(claim=<fact present in corpus>, document_id=doc_id) → verification_status verified, ProvenanceChain has ≥1 citation with valid document_id, page_number; bbox from source or null.
- Unit test: empty corpus or no match from both tools → unverifiable, empty citations, no exception. Spec 08 §6.3: verification determined solely from retrieval results and comparison to claim.

**Referenced specs:** [06 §7](specs/06-query-agent-and-provenance-spec.md), [08 §6](specs/08-data-layer-spec.md), [07 §7.2](specs/07-models-schemas-spec.md).

---

## P4-T005 — LangGraph query agent with three tools

**Description:** Implement the **Query Interface Agent** in `src/agents/query_agent.py` as a **LangGraph** agent with **exactly three tools** per [spec 06 §3](specs/06-query-agent-and-provenance-spec.md) and plan §2.1. **Tools:** (1) **pageindex_navigate** — topic, optional document_id, top_n (default 3); load PageIndex, score sections, return top-N with id, title, page_start, page_end, summary, ldu_ids. (2) **semantic_search** — query, optional document_ids, optional section_constraint (from pageindex_navigate), top_k; call vector store search (P4-T002); return LDUs with provenance fields. (3) **structured_query** — query, optional document_ids; safe parameterized FactTable query (spec 08 §5); return rows with entity, metric, value, unit, period, source_reference; empty list when no match. **Orchestration:** Graph with tool nodes and conditional routing; agent chooses tools and order (navigational → pageindex_navigate then semantic_search; numerical → structured_query then semantic_search if empty). **Every response:** answer text + **ProvenanceChain** built via P4-T003 from cited LDUs and/or fact rows. No raw user SQL; config: top_k, top_n, timeouts, logging (timestamp, query, tools invoked, result count, latency).

**Files to change:**
- `src/agents/query_agent.py` — LangGraph graph, bindings for pageindex_navigate, semantic_search, structured_query, response builder with ProvenanceChain
- Config — top_k, top_n, timeouts, tool routing (if configurable)
- Wire to PageIndex loader, vector store (P4-T002), FactTable reader (P4-T001), provenance helpers (P4-T003)

**Acceptance criteria:**
- Agent exposes only these three tools; no other tools for answering. Example run: natural-language question → answer + ProvenanceChain with ≥1 citation (document_name, page_number, bbox, content_hash for LDU-backed).
- Navigational query: agent calls pageindex_navigate then semantic_search with section_constraint; citations from narrowed sections. Numerical query with FactTable: agent uses structured_query; answer + citations from source_reference. FactTable empty or no match: fallback to semantic_search, answer + ProvenanceChain from LDUs (no crash).
- When no tool returns results, answer indicates no relevant content; ProvenanceChain has empty items (no invented citations). Config change (e.g. top_k) affects behavior; queries logged with required fields.

**Referenced specs:** [06 §3](specs/06-query-agent-and-provenance-spec.md), [06 §4](specs/06-query-agent-and-provenance-spec.md), [08 §4](specs/08-data-layer-spec.md), [08 §5](specs/08-data-layer-spec.md), [plan §2.1](plans/phase-4-query-provenance.plan.md), [plan §3](plans/phase-4-query-provenance.plan.md).

---

## P4-T006 — Generate QAExample artifacts (12 total: 3 per class) with full ProvenanceChain

**Description:** Implement **QAExample** production per [spec 07 §7.3](specs/07-models-schemas-spec.md) and plan §2.4. **QAExample** fields: query (or claim for audit), answer, provenance (ProvenanceChain with items and optional verification_status). **Deliverable:** Generate **12 QAExample artifacts** in total, **3 per class**. Classes: (1) **Q&A — general** — natural-language question answered via semantic_search (and optionally pageindex_navigate); (2) **Q&A — numerical** — question answered via structured_query (FactTable); (3) **Audit — verified** — claim that is supported by the corpus (verified + citations); (4) **Audit — unverifiable** — claim that is not in the corpus (unverifiable, no citations). Each of the 4 classes has 3 examples; each example is a QAExample with full ProvenanceChain (citations with document_name, page_number, bbox, content_hash where required; for unverifiable, items empty and verification_status unverifiable). Output: persisted artifacts (e.g. JSON or JSONL under `.refinery/qa_examples/` or config path) or test fixture that produces and asserts 12 QAExamples. Supports acceptance “example Q&A with ProvenanceChain” and audit evidence (verified vs unverifiable).

**Files to change:**
- `src/models/` — QAExample (Pydantic or dict schema) per spec 07 §7.3
- Script or test module — run query agent and audit mode to produce 12 QAExamples (3 per class), serialize to artifact path
- Config — output path for QAExample artifacts (optional)

**Acceptance criteria:**
- 12 QAExamples produced: 3 Q&A general, 3 Q&A numerical, 3 audit verified, 3 audit unverifiable. Each QAExample has query (or claim), answer, provenance (ProvenanceChain).
- For Q&A and audit-verified: ProvenanceChain has ≥1 citation; each citation has document_name, document_id, page_number, bbox (for LDU), content_hash (for LDU). For audit-unverifiable: ProvenanceChain items empty, verification_status unverifiable.
- Artifacts persist (file or test output) and can be loaded for inspection or evaluation. Unit test or script asserts count (12) and per-class count (3 per class) and required fields on each QAExample.

**Referenced specs:** [07 §7.3](specs/07-models-schemas-spec.md), [06 §4](specs/06-query-agent-and-provenance-spec.md), [plan §2.4](plans/phase-4-query-provenance.plan.md), [plan §7.4](plans/phase-4-query-provenance.plan.md).

---

## Phase 4 completion

When P4-T001 through P4-T006 are complete and their acceptance criteria met, Phase 4 plan acceptance checks are satisfied: SQLite FactTable schema and Fact extractor, ChromaDB vector store (ingestion + query API), ProvenanceChain helpers (bbox + page + content_hash), Audit Mode (verified/unverifiable, no fake citations), LangGraph query agent with three tools, and 12 QAExample artifacts (3 per class) with full ProvenanceChain.
