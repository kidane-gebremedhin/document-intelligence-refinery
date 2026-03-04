# Phase 4: Query Interface Agent & Provenance Layer — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Spec:** [06 – Query Agent & Provenance](../specs/06-query-agent-and-provenance-spec.md).  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§7 ProvenanceChain, §8 FactRecord).  
**Target:** Phase 4 — Build the interface that makes the refinery useful and auditable; answer questions with traceable evidence.

---

## 1. Goal

**Answer questions with traceable evidence.** The Query Interface Agent is the user-facing surface: it accepts natural-language questions, uses PageIndex, vector search, and (optionally) structured fact lookup to gather evidence, and returns an answer **plus a ProvenanceChain**—a list of citations (document name, page number, bounding box, content_hash) so every claim can be verified against the source. The Refinery Guide: "Every answer must include provenance: the document name, page number, and bounding box of the source." Audit mode extends this: given a **claim**, the system either **verifies** it with a citation or returns **"unverifiable"** when no evidence exists.

Phase 4 delivers: (1) a query agent with three tools (pageindex_navigate, semantic_search, structured_query); (2) ProvenanceChain on every answer with bbox, page, and content_hash; (3) FactTable in SQLite for numerical/financial facts and structured_query; (4) Audit mode for claim verification. The pipeline becomes **useful** (users can ask questions) and **auditable** (every answer is traceable to the document).

---

## 2. Query Agent Tools

The agent is implemented as a **LangGraph agent** (or equivalent) with three tools. The agent chooses which tool(s) to call based on query intent. Tool semantics are defined here; graph structure is implementation detail.

### 2.1 pageindex_navigate

- **Purpose:** Traverse the PageIndex to find sections relevant to a **topic** before vector search (PageIndex-first retrieval).
- **Inputs:** `topic` (natural language), optional `document_id`, optional `top_n` (e.g. 3).
- **Behavior:** Score sections by relevance to the topic using title, summary, key_entities, data_types_present. Return the top-N sections with id, title, page_start, page_end, summary, ldu_ids (or equivalent). No vector search; output is used to **restrict** the scope of a subsequent `semantic_search` (e.g. only LDUs in those sections).
- **When used:** Navigational or section-specific queries ("Where is the auditor's opinion?", "What section discusses risk factors?"). Long documents where naive vector search is noisy.

### 2.2 semantic_search

- **Purpose:** Retrieve LDUs by **semantic similarity** to the query (standard RAG retrieval).
- **Inputs:** `query`, optional `document_ids`, optional `section_constraint` (from pageindex_navigate), optional `top_k`.
- **Behavior:** Embed the query; search the vector store. If section_constraint is provided, filter LDUs to those sections (before or after search). Return ranked LDUs with content, document_id, ldu_id, page_refs, bounding_box, content_hash, parent_section—so each result can be turned into a Citation.
- **When used:** Whenever context is needed for an answer. May follow pageindex_navigate (PageIndex-first) or be used alone. Queries that require reading text: "What does the report say about X?", "Summarize the key findings."

### 2.3 structured_query

- **Purpose:** Execute a query over the **FactTable** (SQLite) for precise numerical or factual lookups.
- **Inputs:** `query` (natural language or parameterized), optional `document_ids`.
- **Behavior:** Map the query to a FactTable/SQL query (e.g. by templates, decomposition, or LLM). Execute against SQLite. Return rows with entity, metric, value, unit, period, and **source_reference** (for provenance). Each fact must be resolvable to a Citation (document_id, page, and ideally bbox/content_hash).
- **When used:** Queries asking for specific numbers: "What was revenue in Q3 2024?", "Total tax expenditure for 2020." If FactTable is empty or returns no match, the agent falls back to semantic_search.

### 2.4 Tool orchestration

- **Navigational** → pageindex_navigate, then optionally semantic_search with section constraint.
- **Numerical/factual** → structured_query first; if empty, semantic_search.
- **Synthesis/narrative** → pageindex_navigate + semantic_search, or semantic_search alone.
- **Hybrid** — Multiple tools; combine results and merge ProvenanceChain from all cited sources.

---

## 3. ProvenanceChain Requirements (bbox + page + content_hash)

Every answer must include a **ProvenanceChain**: a list of **citations**, one per distinct source (LDU or FactTable row). The constitution requires **spatial provenance**; the Refinery Guide requires document name, page number, and bounding box.

### 3.1 Required fields per citation

- **document_name** — Human-readable (e.g. filename, report title). Resolved from document_id.
- **document_id** — Stable identifier for the document.
- **page_number** — 1-based page where the cited content appears.
- **bounding_box** — Spatial coordinates (e.g. x0, top, x1, bottom) so the user can locate the content in the PDF. **Required** for citations from LDUs; for FactTable rows, bbox may be null if not stored, but page_number must be present.
- **content_hash** — Stable hash of the source content (from the LDU). Enables verification that the source has not changed; required for LDU-backed citations. For FactTable, source_reference should be resolvable to at least page and ideally to an LDU with content_hash.

### 3.2 Optional fields

- **snippet** — Short excerpt of the cited content (e.g. 100–200 chars).
- **ldu_id**, **chunk_type** — For traceability and "this came from a table" context.

### 3.3 Invariants

- No citation may be emitted with missing required fields (document_name, document_id, page_number, bounding_box for LDU sources; content_hash for LDU sources). For FactTable-only citations, bounding_box may be null if not in source_reference.
- The ProvenanceChain must be **actionable**: a user with the original PDF can open the cited page and locate the content using the bounding box (when bbox is present).
- Citations must come **only** from actually retrieved LDUs or FactTable rows. No hallucinated page numbers or bboxes.

---

## 4. FactTable Extraction into SQLite (schema + extraction rules)

### 4.1 Schema (minimal)

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

### 4.2 Extraction rules (conceptual)

- **Target documents:** Financial reports, tax reports, audit reports (e.g. domain_hint=financial or table-heavy). Extraction may run as a post-chunking step or a separate pipeline stage.
- **Source content:** Table LDUs (headers + rows) and optionally narrative LDUs that contain key figures (e.g. "Revenue for the quarter was $4.2B").
- **Extraction method:** LLM-based extraction, rule-based parsing of table rows, or hybrid. Output must conform to the schema. Entity, metric, value, unit, period should be normalized (e.g. consistent units, date formats) where possible.
- **Provenance:** When extracting from an LDU, store source_reference that links to that LDU (and thus to page, bbox, content_hash). When extracting from a table row, one source_reference per row or per table region is acceptable; spec leaves granularity to implementation.
- **Configurability:** Which documents to run extraction on (e.g. by domain_hint), which metrics to extract, and any thresholds should be configurable (config-over-code).

---

## 5. Audit Mode: verify claim → citation-backed or unverifiable

**Audit mode** answers: "Does the document (or corpus) support this claim?"

### 5.1 Input

- **claim** — The statement to verify (e.g. "The report states revenue was $4.2B in Q3 2024").
- **document_id** (optional) — If set, search only that document; otherwise corpus-wide.

### 5.2 Behavior

1. **Parse the claim** — Extract key entities and values (e.g. metric=revenue, value=4.2B, period=Q3 2024).
2. **Query FactTable** — If the claim is numerical, run structured_query for matching facts. Compare returned values to the claim (exact or consistent, e.g. "approximately $4.2B" supports "$4.2B").
3. **Query semantic search** — Run semantic_search with the claim (or reformulation) to find LDUs that might support or contradict it.
4. **Evaluate** — Decide whether any retrieved content supports the claim (value, metric, period match; semantic match for narrative claims).
5. **Output:**
   - **Verified** — Return confirmation and a **ProvenanceChain** with the supporting citation(s). Example: "Yes. The report states revenue of $4.2B in Q3 2024. See [Citation: Document X, p. 42, bbox (...)]."
   - **Unverifiable** — Return an explicit **unverifiable** signal. Example: "The claim could not be verified. No supporting source was found in the corpus." **Do not** invent a citation. **Do not** say "the document states X" when it does not.

### 5.3 Invariants

- **Never** return a citation for a claim that is not supported by a retrieved source. If no source supports the claim, the response must be unverifiable (no citation).
- **Never** hallucinate page number or bbox. Citations are only from actual LDUs or FactTable rows.
- The response must clearly distinguish: **verified** (with citation) vs. **unverifiable** (no citation).

### 5.4 When to return "Unverifiable"

- No supporting source found in the corpus.
- Ambiguous or conflicting sources (optionally: "Multiple sources with conflicting information").
- Source found but does not match the claim (e.g. different value or period).
- Empty corpus or document not indexed.

---

## 6. Acceptance Checks

### 6.1 Example Q&A with ProvenanceChain items

- Run the query agent on at least one **natural-language question** (e.g. "What was revenue in Q3 2024?" or "What are the main risk factors?" or "Show me the auditor's opinion") over a document (or corpus) that has been through Stages 1–4 and has LDUs (and optionally FactTable) populated.
- **Evidence:** The response includes both an **answer** and a **ProvenanceChain** with at least one **citation**. Each citation includes: document_name, document_id, page_number, bounding_box, content_hash (for LDU-backed citations). Optional: snippet, ldu_id, chunk_type.
- **Evidence:** A human can open the cited document at the cited page and use the bounding box to locate the source content. (Manual check or script that validates citation fields are present and non-empty.)

### 6.2 Audit mode returns "unverifiable" when no evidence exists

- **Scenario 1:** Run audit mode with a **claim that is not in the corpus** (e.g. "The report states revenue was $99.9B in Q1 2099" for a document that does not contain that). The system must return **unverifiable** (or equivalent) and must **not** return any citation. Evidence: test or script that asserts the response indicates unverifiable and that no citation is present (or citation list is empty).
- **Scenario 2:** Run audit mode with a **claim that is in the corpus** (e.g. a fact that appears in an LDU or FactTable). The system must return **verified** (or equivalent) and a ProvenanceChain with at least one citation that points to the supporting source. Evidence: test or script that asserts verified + non-empty citations when evidence exists.
- **Invariant check:** Audit mode never invents a citation. When no evidence exists, the response text must clearly state that the claim could not be verified (e.g. "No supporting source was found" or "unverifiable").

### 6.3 Tool behavior and fallbacks

- **pageindex_navigate:** At least one run where the agent uses pageindex_navigate (e.g. for a section-specific query) and then semantic_search with section constraint; ProvenanceChain cites LDUs from the narrowed set. Evidence: trace or log showing both tools used and citations from the expected sections.
- **structured_query:** For a numerical question over a document with FactTable populated, the agent uses structured_query and returns an answer with ProvenanceChain derived from source_reference. Evidence: answer reflects FactTable data and citation resolves to the correct document/page (and optionally LDU).
- **Fallback:** When FactTable is empty or returns no match, the agent falls back to semantic_search and still returns an answer with ProvenanceChain from LDUs. No crash; answer may be from semantic search only.

### 6.4 Configurability and logging

- Tool selection heuristics, top_k, top_n, timeouts are configurable (config-over-code). Evidence: changing a config value (e.g. top_k) changes behavior where applicable.
- Queries (and tool calls) are logged with timestamp, query text, tools invoked, result count, latency. Evidence: at least one query produces a log entry with the required fields.

---

**Deliverables (Refinery Guide §8):** Final repo requires `src/agents/query_agent.py` (LangGraph agent with pageindex_navigate, semantic_search, structured_query), FactTable + SQLite, vector store ingestion (ChromaDB/FAISS), Audit Mode (claim verification). See [spec 01 §9](../specs/01-document-intelligence-refinery-system.md#9-deliverables-refinery-guide-8).

**Version:** 1.0  
**Plan status:** Plan only; no code. Implementation follows this plan and spec 06; models follow spec 07.
