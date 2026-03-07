# Phase 4: Query Interface Agent & Provenance Layer — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Specs:** [06 – Query Agent & Provenance](../specs/06-query-agent-and-provenance-spec.md), [08 – Data Layer](../specs/08-data-layer-spec.md).  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§7 ProvenanceChain, §7.3 QAExample, §8 FactRecord).  
**Target:** Phase 4 — Build the interface that makes the refinery useful and auditable; answer questions with traceable evidence.

---

## 1. Goal

**Answer questions with traceable evidence.** The Query Interface Agent is the user-facing surface: it accepts natural-language questions, uses PageIndex, vector search, and (optionally) structured fact lookup to gather evidence, and returns an answer **plus a ProvenanceChain**—a list of citations (document name, page number, bounding box, content_hash) so every claim can be verified against the source. The Refinery Guide: "Every answer must include provenance: the document name, page number, and bounding box of the source." Audit mode extends this: given a **claim**, the system either **verifies** it with a citation or returns **"unverifiable"** when no evidence exists.

Phase 4 delivers: (1) a LangGraph query agent in `src/agents/query_agent.py` with exactly three tools; (2) ProvenanceChain on every answer with bbox, page, and content_hash; (3) FactTable extractor and SQLite backend for numerical/financial facts; (4) Audit mode with verification flow (citations or unverifiable); (5) Q&A artifact production as QAExample objects that include ProvenanceChain. The pipeline becomes **useful** (users can ask questions) and **auditable** (every answer is traceable to the document).

---

## 2. Implementation Layout and Deliverables

### 2.1 Query agent: `src/agents/query_agent.py`

- **LangGraph agent with 3 tools** — The single entry point for the query interface. Implements a LangGraph (or equivalent) agent that exposes **exactly three tools**: pageindex_navigate, semantic_search, structured_query (spec 06 §3). No other tools for answering or audit. The agent chooses which tool(s) to call and in what order based on query intent; graph structure (nodes, edges, conditional routing) is implementation-defined.
- **Entry point** — Spec 01 §9 names `src/agents/query_agent.py` as the deliverable. The module (or package) wires the three tools to the data layer (PageIndex from disk, vector store, FactTable) and returns an answer plus ProvenanceChain for every query and audit call.

### 2.2 FactTable extractor + SQLite backend

- **FactTable extractor** — Consumes LDUs (from Stage 3); extracts facts per [08 – Data Layer](../specs/08-data-layer-spec.md) §2 (what qualifies as a fact, mapping to entity/value/unit/period/category_path, source_reference). Runs as a post-chunking step or separate stage; may be triggered after index or from a dedicated pipeline step.
- **SQLite backend** — FactTable is stored in SQLite at `.refinery/fact_table.db` (or configured path). Schema and indexes per spec 08 §3 (facts table, source_reference NOT NULL, indexes for document_id, metric, period, etc.). The **structured_query** tool reads from this database via safe, parameterized queries (spec 08 §5); no raw user SQL.

### 2.3 Audit Mode verification flow (citations or unverifiable)

- **Flow** — Given a **claim**, the system (1) queries FactTable via structured_query and semantic_search with the claim (or reformulation); (2) builds provenance items only from returned fact rows and LDUs (spec 08 §6); (3) evaluates whether any retrieved content supports the claim; (4) outputs **either** (a) **Verified** — ProvenanceChain with one or more citations (document_name, page_number, bbox, content_hash where available), verification_status = verified, **or** (b) **Unverifiable** — explicit unverifiable flag, ProvenanceChain with **no** citations (empty list), verification_status = unverifiable. Never fake verification: no citation when no supporting source exists (spec 06 §7, spec 08 §6).

### 2.4 Q&A artifact production: QAExample with ProvenanceChain

- **Requirement** — For acceptance runs, logging, or evaluation, the pipeline must be able to produce **QAExample** (or equivalent) objects that pair a query (or claim for audit) with the answer and its **ProvenanceChain** (spec 07 §7.3). Each QAExample includes: query (or claim), answer text, provenance (citations + optional verification_status). This supports “example Q&A with ProvenanceChain” acceptance and audit evidence (verified vs unverifiable). Implementation may use a Pydantic model or dict; the plan requires that at least one acceptance path produces such artifacts (e.g. one Q&A run and one audit run captured as QAExample-like records).

---

## 3. Query Agent Tools

The agent is implemented as a **LangGraph agent** (or equivalent) with three tools (see §2.1). The agent chooses which tool(s) to call based on query intent. Tool semantics are defined here; graph structure is implementation detail.

### 3.1 pageindex_navigate

- **Purpose:** Traverse the PageIndex to find sections relevant to a **topic** before vector search (PageIndex-first retrieval).
- **Inputs:** `topic` (natural language), optional `document_id`, optional `top_n` (e.g. 3).
- **Behavior:** Score sections by relevance to the topic using title, summary, key_entities, data_types_present. Return the top-N sections with id, title, page_start, page_end, summary, ldu_ids (or equivalent). No vector search; output is used to **restrict** the scope of a subsequent `semantic_search` (e.g. only LDUs in those sections).
- **When used:** Navigational or section-specific queries ("Where is the auditor's opinion?", "What section discusses risk factors?"). Long documents where naive vector search is noisy.

### 3.2 semantic_search

- **Purpose:** Retrieve LDUs by **semantic similarity** to the query (standard RAG retrieval).
- **Inputs:** `query`, optional `document_ids`, optional `section_constraint` (from pageindex_navigate), optional `top_k`.
- **Behavior:** Embed the query; search the vector store. If section_constraint is provided, filter LDUs to those sections (before or after search). Return ranked LDUs with content, document_id, ldu_id, page_refs, bounding_box, content_hash, parent_section—so each result can be turned into a Citation.
- **When used:** Whenever context is needed for an answer. May follow pageindex_navigate (PageIndex-first) or be used alone. Queries that require reading text: "What does the report say about X?", "Summarize the key findings."

### 3.3 structured_query

- **Purpose:** Execute a query over the **FactTable** (SQLite) for precise numerical or factual lookups.
- **Inputs:** `query` (natural language or parameterized), optional `document_ids`.
- **Behavior:** Map the query to a FactTable/SQL query (e.g. by templates, decomposition, or LLM). Execute against SQLite. Return rows with entity, metric, value, unit, period, and **source_reference** (for provenance). Each fact must be resolvable to a Citation (document_id, page, and ideally bbox/content_hash).
- **When used:** Queries asking for specific numbers: "What was revenue in Q3 2024?", "Total tax expenditure for 2020." If FactTable is empty or returns no match, the agent falls back to semantic_search.

### 3.4 Tool orchestration

- **Navigational** → pageindex_navigate, then optionally semantic_search with section constraint.
- **Numerical/factual** → structured_query first; if empty, semantic_search.
- **Synthesis/narrative** → pageindex_navigate + semantic_search, or semantic_search alone.
- **Hybrid** — Multiple tools; combine results and merge ProvenanceChain from all cited sources.

---

## 4. ProvenanceChain Requirements (bbox + page + content_hash)

Every answer must include a **ProvenanceChain**: a list of **citations**, one per distinct source (LDU or FactTable row). The constitution requires **spatial provenance**; the Refinery Guide requires document name, page number, and bounding box.

### 4.1 Required fields per citation

- **document_name** — Human-readable (e.g. filename, report title). Resolved from document_id.
- **document_id** — Stable identifier for the document.
- **page_number** — 1-based page where the cited content appears.
- **bounding_box** — Spatial coordinates (e.g. x0, top, x1, bottom) so the user can locate the content in the PDF. **Required** for citations from LDUs; for FactTable rows, bbox may be null if not stored, but page_number must be present.
- **content_hash** — Stable hash of the source content (from the LDU). Enables verification that the source has not changed; required for LDU-backed citations. For FactTable, source_reference should be resolvable to at least page and ideally to an LDU with content_hash.

### 4.2 Optional fields

- **snippet** — Short excerpt of the cited content (e.g. 100–200 chars).
- **ldu_id**, **chunk_type** — For traceability and "this came from a table" context.

### 4.3 Invariants

- No citation may be emitted with missing required fields (document_name, document_id, page_number, bounding_box for LDU sources; content_hash for LDU sources). For FactTable-only citations, bounding_box may be null if not in source_reference.
- The ProvenanceChain must be **actionable**: a user with the original PDF can open the cited page and locate the content using the bounding box (when bbox is present).
- Citations must come **only** from actually retrieved LDUs or FactTable rows. No hallucinated page numbers or bboxes.

---

## 5. FactTable Extraction into SQLite (schema + extraction rules)

### 5.1 Schema (minimal)

The FactTable is stored in **SQLite**. Minimal schema per spec 06 and spec 07 §8:

| Column | Type | Description |
|--------|------|-------------|
| **id** | integer (PK) | Auto-increment. |
| **document_id** | string | Document from which the fact was extracted. |
| **entity** | string | Subject (e.g. "Commercial Bank of Ethiopia", "Revenue"). |
| **metric** | string | Measured quantity (e.g. "revenue", "total_assets", "net_income"). |
| **value** | string or numeric | The value (e.g. "4.2", "4.2B"). Normalization is implementation-defined. |
| **unit** | string (optional) | Unit (e.g. "ETB", "USD", "%"). |
| **period** | string (optional) | Time period (e.g. "Q3 2024", "FY 2023"). |
| **source_reference** | string | Provenance: must be resolvable to at least page_number and ideally to bbox and content_hash (e.g. "page:42,ldu:ldu_015" or "page:42"). |

**Invariant:** Every fact has `source_reference` so that structured_query results can be turned into ProvenanceChain citations.

### 5.2 Extraction rules (conceptual)

- **Target documents:** Financial reports, tax reports, audit reports (e.g. domain_hint=financial or table-heavy). Extraction may run as a post-chunking step or a separate pipeline stage.
- **Source content:** Table LDUs (headers + rows) and optionally narrative LDUs that contain key figures (e.g. "Revenue for the quarter was $4.2B").
- **Extraction method:** LLM-based extraction, rule-based parsing of table rows, or hybrid. Output must conform to the schema. Entity, metric, value, unit, period should be normalized (e.g. consistent units, date formats) where possible.
- **Provenance:** When extracting from an LDU, store source_reference that links to that LDU (and thus to page, bbox, content_hash). When extracting from a table row, one source_reference per row or per table region is acceptable; spec leaves granularity to implementation.
- **Configurability:** Which documents to run extraction on (e.g. by domain_hint), which metrics to extract, and any thresholds should be configurable (config-over-code).

---

## 6. Audit Mode: verify claim → citation-backed or unverifiable

**Audit mode** answers: "Does the document (or corpus) support this claim?"

### 6.1 Input

- **claim** — The statement to verify (e.g. "The report states revenue was $4.2B in Q3 2024").
- **document_id** (optional) — If set, search only that document; otherwise corpus-wide.

### 6.2 Behavior

1. **Parse the claim** — Extract key entities and values (e.g. metric=revenue, value=4.2B, period=Q3 2024).
2. **Query FactTable** — If the claim is numerical, run structured_query for matching facts. Compare returned values to the claim (exact or consistent, e.g. "approximately $4.2B" supports "$4.2B").
3. **Query semantic search** — Run semantic_search with the claim (or reformulation) to find LDUs that might support or contradict it.
4. **Evaluate** — Decide whether any retrieved content supports the claim (value, metric, period match; semantic match for narrative claims).
5. **Output:**
   - **Verified** — Return confirmation and a **ProvenanceChain** with the supporting citation(s). Example: "Yes. The report states revenue of $4.2B in Q3 2024. See [Citation: Document X, p. 42, bbox (...)]."
   - **Unverifiable** — Return an explicit **unverifiable** signal. Example: "The claim could not be verified. No supporting source was found in the corpus." **Do not** invent a citation. **Do not** say "the document states X" when it does not.

### 6.3 Invariants

- **Never** return a citation for a claim that is not supported by a retrieved source. If no source supports the claim, the response must be unverifiable (no citation).
- **Never** hallucinate page number or bbox. Citations are only from actual LDUs or FactTable rows.
- The response must clearly distinguish: **verified** (with citation) vs. **unverifiable** (no citation).

### 6.4 When to return "Unverifiable"

- No supporting source found in the corpus.
- Ambiguous or conflicting sources (optionally: "Multiple sources with conflicting information").
- Source found but does not match the claim (e.g. different value or period).
- Empty corpus or document not indexed.

---

## 7. Acceptance Checks

### 7.1 structured_query returns correct facts from SQLite

- **Requirement:** The **structured_query** tool must return **correct facts** from the SQLite FactTable when the query matches stored data. Evidence:
  - With FactTable populated (e.g. rows with entity, metric, value, period, source_reference), run structured_query with a natural-language or parameterized query that targets those facts (e.g. “revenue Q3 2024” or equivalent). The returned rows must match the expected entity, metric, value, unit, period, and include non-empty source_reference.
  - Unit test or script: insert known facts into the FactTable; call structured_query with the corresponding query; assert returned rows contain the expected values and source_reference. When document_ids filter is applied, results must be restricted to that document.
  - When no row matches, structured_query returns an empty list (no exception). Evidence: test with a query that does not match any fact; assert empty result.

### 7.2 semantic_search returns LDUs with provenance

- **Requirement:** The **semantic_search** tool must return **LDUs** (or LDU-like results) that include everything needed to build **provenance** (Citation). Evidence:
  - Run semantic_search with a query over a populated vector store. Each returned result must include: document_id, ldu_id (or equivalent), page_refs (or first page), bounding_boxes or first bbox, content_hash, content (and optionally parent_section). From these, the agent (or provenance layer) can build a Citation with document_name, page_number, bbox, content_hash (spec 06 §4).
  - Unit test or script: run semantic_search; assert each result has the required fields for provenance; assert that building a ProvenanceItem/Citation from the result succeeds and has non-empty document_id, page_number, content_hash (and bbox for LDU-backed).
  - With section_constraint (e.g. from pageindex_navigate), results must be restricted to LDUs within those sections. Evidence: test with section filter; assert returned LDUs belong to the constrained set.

### 7.3 Audit mode refuses unverifiable claims

- **Requirement:** **Audit mode** must **refuse** to verify claims that have no supporting source—i.e. return **unverifiable** and **no citations**. Evidence:
  - Run audit mode with a **claim that is not in the corpus** (e.g. “The report states revenue was $99.9B in Q1 2099” for a document that does not contain that). The system must return **unverifiable** (or equivalent) and must **not** return any citation (ProvenanceChain items empty). Response text must clearly state that the claim could not be verified (e.g. “No supporting source was found” or “unverifiable”).
  - Unit test or script: audit(claim=<nonexistent fact>, document_id=…) → assert verification_status is unverifiable (or equivalent); assert citation list is empty; assert response text indicates unverifiable. **Audit mode must never invent a citation** for an unverifiable claim.
  - Contrast: Run audit mode with a **claim that is in the corpus**; assert verified + at least one citation with valid document_id, page_number, and (when available) bbox from the source.

### 7.4 Example Q&A with ProvenanceChain and QAExample artifact

- Run the query agent on at least one **natural-language question** over a document (or corpus) that has been through Stages 1–4 and has LDUs (and optionally FactTable) populated. **Evidence:** The response includes an **answer** and a **ProvenanceChain** with at least one citation (document_name, document_id, page_number, bounding_box, content_hash for LDU-backed). Produce a **QAExample** (or equivalent) object that captures query, answer, and ProvenanceChain for the acceptance artifact.
  - A human (or script) can open the cited document at the cited page and use the bounding box to locate the source content.

### 7.5 Tool behavior and fallbacks

- **pageindex_navigate:** At least one run where the agent uses pageindex_navigate then semantic_search with section constraint; ProvenanceChain cites LDUs from the narrowed set. Evidence: trace or log showing both tools used and citations from the expected sections.
- **structured_query:** For a numerical question over a document with FactTable populated, the agent uses structured_query and returns an answer with ProvenanceChain derived from source_reference. Evidence: answer reflects FactTable data and citation resolves to the correct document/page (and optionally LDU).
- **Fallback:** When FactTable is empty or returns no match, the agent falls back to semantic_search and still returns an answer with ProvenanceChain from LDUs. No crash; answer may be from semantic search only.

### 7.6 Configurability and logging

- Tool selection heuristics, top_k, top_n, timeouts are configurable (config-over-code). Evidence: changing a config value (e.g. top_k) changes behavior where applicable.
- Queries (and tool calls) are logged with timestamp, query text, tools invoked, result count, latency. Evidence: at least one query produces a log entry with the required fields.

---

**Deliverables (Refinery Guide §8):** Final repo requires **`src/agents/query_agent.py`** (LangGraph agent with exactly three tools: pageindex_navigate, semantic_search, structured_query), **FactTable extractor + SQLite backend** (spec 08), vector store ingestion (ChromaDB per spec 08), **Audit Mode** with verification flow (citations or unverifiable; never fake verification), and **Q&A artifact production** (QAExample objects with ProvenanceChain). See [spec 01 §9](../specs/01-document-intelligence-refinery-system.md#9-deliverables-refinery-guide-8).

**Version:** 1.0  
**Plan status:** Plan only; no code. Implementation follows this plan and spec 06; models follow spec 07.
