# Spec: Stage 4 – PageIndex Builder

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Upstream:** [03 – Multi-Strategy Extraction Engine](03-multi-strategy-extraction-engine.md), [04 – Semantic Chunking Engine & LDUs](04-semantic-chunking-and-ldu-spec.md)  
**Constitution alignment:** PageIndex-first retrieval; hierarchical section identification (inspired by VectifyAI's PageIndex); typed Pydantic contracts; config-over-code for thresholds and summarization.

---

## 1. Purpose

The PageIndex Builder produces a **smart table of contents** for each document—a hierarchical navigation structure that an LLM or retrieval agent can traverse to locate information without reading the entire document. It directly addresses the **needle-in-a-haystack problem** for long-document RAG.

### The needle-in-a-haystack problem

In a 400-page financial report or technical assessment, embedding-searching across 10,000+ chunks is inefficient and often imprecise:

- **Noise:** Semantic search returns many marginally relevant chunks; the truly relevant section may rank below less useful but superficially similar text.
- **Cost:** Embedding and searching every chunk at query time is expensive and slow.
- **Context loss:** The retrieved chunks lack structural context—the user asked about "capital expenditure projections" but the system has no notion that such content lives in "Section 5: Capital Budget" rather than scattered across the document.

Without a navigation layer, the retrieval agent treats the document as a flat bag of chunks. With a PageIndex, the agent can **first** traverse the tree to find the relevant section(s), **then** retrieve only the LDUs within those sections. The Refinery Guide states: "When a user asks 'What are the capital expenditure projections for Q3?', the PageIndex allows the retrieval agent to first navigate to the relevant section, then retrieve only the relevant chunks—rather than embedding-searching a 10,000-chunk corpus."

### Why a "smart" table of contents

A naive table of contents (e.g., from PDF metadata) is often incomplete, inconsistent, or missing. The PageIndex is **smart** because it:

- Derives section structure from document content (headings, LDU boundaries, reading order) rather than relying on metadata.
- Attaches rich metadata to each section: summary (LLM-generated), key entities, data types present (tables, figures, equations).
- Supports **topic-based traversal**—given a topic string (e.g., "capital expenditure"), the system can score sections and return the top-N most relevant ones before vector search.

The result is **PageIndex-first retrieval**: navigate to the right region of the document first, then retrieve chunks within that region. This improves precision and reduces cost (fewer chunks to embed and search).

---

## 2. Inputs

The PageIndex Builder consumes:

### 2.1 List of LDUs (required)

The output of Stage 3 (Semantic Chunking Engine). Each LDU provides:

| Signal | Field | Use in PageIndex |
|--------|-------|------------------|
| Section membership | `parent_section` | Associates LDUs with sections; sections are derived from headings, and `parent_section` propagates section context to child LDUs. |
| Content type | `chunk_type` | Drives `data_types_present` (tables, figures) per section. |
| Page extent | `page_refs` | Bounds section `page_start` and `page_end`. |
| Content | `content` | Source for section summarization and key entity extraction. |
| Spatial provenance | `bounding_box` | Used for section spatial bounds when aggregating LDUs. |

LDUs must be in **reading order**. The PageIndex Builder traverses them to infer section boundaries and hierarchy.

### 2.2 Heading and section signals

- **LDUs with `chunk_type` in `heading`, `section_header`** — These LDUs' `content` is the section title. Their `page_refs` and position in reading order define section start.
- **`parent_section`** — For LDUs that are not headings, `parent_section` indicates which section contains them. Used to assign LDUs to sections when headings are present.
- **Numbering patterns** — Headings often follow patterns (e.g., "1.", "1.1", "1.1.1"). These patterns can drive hierarchy (section → subsection → subsubsection).

### 2.3 Document metadata (optional)

- **document_id** — Correlates with DocumentProfile and downstream storage paths.
- **page_count** — Upper bound for `page_end`; useful for validation.

### 2.4 Pre-conditions

- LDUs are non-empty and valid (per LDU spec invariants).
- At least one LDU has `page_refs`. Documents with no LDUs produce an empty or minimal PageIndex (see §9).

---

## 3. Outputs (PageIndex Tree Schema)

The PageIndex is a **tree**. The root represents the whole document; each child node is a **Section**. The schema is logical; implementations use typed models (e.g. Pydantic).

### 3.1 Top-level PageIndex

| Field | Type | Description |
|-------|------|-------------|
| **document_id** | string | Same as DocumentProfile and LDU document context. |
| **page_count** | integer | Total pages in the document. |
| **root** | Section | Root section (the whole document). May have `title` "Document" or the document title if available. |
| **built_at** | string (optional) | ISO 8601 timestamp when the PageIndex was built. |

### 3.2 Section node (conceptual structure)

Each node in the tree is a **Section**. For Phase 3, every section node **must** support the following fields (required set for topic traversal and retrieval narrowing):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **id** | string | Yes | Unique identifier within the document (e.g. `sec_001`, or path-based `1.2.3`). |
| **title** | string | Yes | Section title. For root, may be "Document" or document title. For leaves, the heading text (e.g. "3.2 Financial Performance"). |
| **page_start** | integer | Yes | 1-based page number where the section begins. |
| **page_end** | integer | Yes | 1-based page number where the section ends. Invariant: `page_end >= page_start`. |
| **child_sections** | list of Section | Yes | Child sections (subsections). Empty list for leaf sections. |
| **key_entities** | list of string | No | Extracted named entities (e.g., organization names, monetary values, dates) that appear in this section. Supports "which section discusses X?" queries. |
| **summary** | string | No | LLM-generated summary, 2–3 sentences. Captures the section's main topic and findings. When summarization is disabled or fails, may be null. |
| **data_types_present** | list of string | No | Content types in this section: `tables`, `figures`, `equations`, `lists`, `paragraphs`, etc. Enables "which section has the revenue table?" queries. |
| **ldu_ids** | list of string | No | IDs of LDUs that belong to this section. Enables direct mapping from section to chunks for retrieval. Required for PageIndex-first narrowing. |
| **depth** | integer (optional) | No | Nesting level (0 = root, 1 = top-level section, etc.). |

**Phase 3 required set for each section node:** `title`, `page_start`, `page_end`, `child_sections`, `key_entities`, `summary` (2–3 sentences when LLM used), `data_types_present`, and `ldu_ids` (or equivalent). These are the minimum for `pageindex_query(topic)` and retrieval narrowing.

### 3.3 Invariants

- **Hierarchy:** `page_start` and `page_end` of a child section must be within the parent's `[page_start, page_end]`.
- **Order:** `child_sections` are in document order (by `page_start`).
- **Coverage:** The union of leaf sections' page ranges should cover the document (with possible gaps for front matter, appendices, or non-section content).
- **Non-overlap:** Sibling sections' page ranges should not overlap (or overlap only at boundaries for contiguous sections).

---

## 4. Section Identification & Hierarchy

Sections and subsections are derived from heading patterns, LDU boundaries, and heuristic rules. The PageIndex Builder does **not** rely on PDF outline or metadata; it infers structure from content.

### 4.1 Primary signal: heading LDUs

- **Headings** — LDUs with `chunk_type` in `heading`, `section_header` provide the strongest signal. Their `content` is the section title; their position in reading order defines section start.
- **Numbering** — Patterns like `"1."`, `"1.1"`, `"1.1.1"`, `"A."`, `"I."` indicate hierarchy. Deeper numbering (more dots or levels) implies deeper nesting. Heuristic: same or increasing indent/nesting level starts a sibling; deeper level starts a child.
- **Page boundary** — A heading's `page_refs` (and the first page of its content) define `page_start`. `page_end` is the last page before the next sibling heading (or end of document).

### 4.2 Secondary signal: LDU boundaries

When headings are weak or missing:

- **Content clustering** — Group consecutive LDUs by proximity (page, reading order). A natural break (e.g., page turn, large vertical gap) may imply a section boundary.
- **parent_section** — If the Chunking Engine populated `parent_section` from extraction-layer headings, use it to assign LDUs to sections. Sections can be created from the set of distinct `parent_section` values.
- **Chunk type transitions** — A run of tables followed by narrative, or a figure block, may suggest a logical subunit. Use as a weak signal when headings are absent.

### 4.3 Heuristic rules

| Rule | Description |
|------|-------------|
| **Numbering hierarchy** | "2.1" is a child of "2"; "2.1.1" is a child of "2.1". If numbering is flat (all "1.", "2.", "3."), treat as sibling top-level sections. |
| **Title-only fallback** | If a heading has no number (e.g., "Executive Summary"), infer level from position: first heading is often top-level; headings after numbered sections may be subsections if indented or styled similarly. |
| **Page continuity** | A section's `page_end` is the page of the last LDU in that section (by reading order) before the next sibling or parent's next sibling. |
| **Root section** | The root spans `page_start=1`, `page_end=page_count`. All top-level sections are its children. |
| **Orphan content** | Content before the first heading (e.g., title page, abstract) may be grouped into a synthetic section (e.g., "Front matter") or attached to the root. |

### 4.4 Configurability

- Numbering regex patterns (e.g., `^\d+\.`, `^\d+\.\d+\.`) and hierarchy mapping should be configurable.
- Minimum section length (e.g., minimum LDUs or pages per section) to avoid over-fragmentation.
- Behavior when no headings exist: flat structure (one section per page or per N pages) vs. single root-only section.

---

## 4.5 Index building algorithm expectations

The PageIndex Builder constructs the tree in a well-defined order. Implementations must satisfy the following expectations:

1. **Section identification (heuristics)** — Traverse LDUs in reading order; use heading/section_header LDUs and numbering patterns (§4.1–4.3) to derive section boundaries and hierarchy. Compute `page_start` and `page_end` for each section. When headings are weak or missing, apply fallbacks (§4.2, §9.1): e.g. flat structure or root-only.
2. **Tree construction** — Build the Section tree: root spans `[1, page_count]`; child sections in document order; child `[page_start, page_end]` within parent range; no overlapping sibling ranges (or only at boundaries).
3. **LDU assignment** — For each section, set `ldu_ids` to the list of LDU ids whose `parent_section` matches the section (or section id) or whose `page_refs` fall within the section's `[page_start, page_end]`.
4. **Section metadata** — Populate `key_entities` (from NER, keywords, or LLM on section LDU content) and `data_types_present` (from `chunk_type` of section LDUs: tables, figures, lists, etc.). Scope: section's LDUs only (or configurable aggregation from descendants).
5. **Optional LLM summarizer** — For each section node, optionally call a fast, cheap LLM with input: section title + concatenated LDU content (truncated). Set `summary` to 2–3 sentences, or leave null on failure or when summarization is disabled. Summarization must not block tree build; on API/timeout failure, leave `summary` null and log.

The algorithm is **deterministic** for a given LDU list and config (except where LLM is used). Section structure must not depend on summarization success.

---

## 5. Section Summarization Requirements

Each section node should have a **summary**: 2–3 sentences that capture the section's main topic and findings. Summaries enable topic-based traversal—the retrieval agent scores sections by relevance to the query using the summary text (and optionally title, key_entities).

### 5.1 Model selection

- Use a **fast, cheap** model (e.g., a small local model, or a low-cost API model like Gemini Flash, GPT-4o-mini). Summarization runs once per section at build time; cost must be bounded.
- Model choice is configurable; the spec does not mandate a specific model.

### 5.2 What the summary must capture

| Requirement | Description |
|-------------|-------------|
| **Main topic** | What the section is about (e.g., "This section discusses capital expenditure projections for FY 2024–25."). |
| **Key findings or data** | If the section contains tables, figures, or enumerated findings, the summary should mention them (e.g., "It includes a table of quarterly projections and a discussion of regional variance."). |
| **2–3 sentences** | Concise; long summaries dilute retrieval quality. Target ~50–100 words. |
| **Self-contained** | The summary should be understandable without reading the section. Enables "Does this section contain what I need?" without fetching LDUs. |

### 5.3 Input to summarization

- **Section content** — Concatenate `content` of all LDUs in the section, truncated if necessary (e.g., first N tokens). Tables can be represented as captions or row summaries to reduce token count.
- **Section title** — Always include; it provides strong semantic signal.
- **data_types_present** — May be passed as context so the model knows to mention "tables" or "figures" when present.

### 5.4 Failure handling

- If summarization fails (API error, timeout), leave `summary` null and log. The section remains usable; topic traversal may fall back to title and key_entities.
- If a section has no LDUs (synthetic or empty), `summary` may be null or a placeholder (e.g., "No content extracted.").

---

## 6. Section Metadata (key_entities, data_types_present)

### 6.1 key_entities

**Purpose:** Support queries like "Which section mentions the Commercial Bank of Ethiopia?" or "Where is the Q3 revenue figure?"

**Population rules:**

- Extract named entities from the section's LDU content. Entity types: organizations, persons, dates, monetary values, locations, key terms (e.g., "capital expenditure", "audit opinion").
- Extraction method: NER (named entity recognition) library, keyword lists, or LLM extraction. Implementation choice; the spec requires that `key_entities` is a list of strings (normalized, deduplicated).
- Limit: e.g., top 10–20 entities per section to avoid noise. Configurable.
- Scope: Only entities that appear in this section's LDUs. Do not propagate from child sections (to keep each section's metadata local).

### 6.2 data_types_present

**Purpose:** Support queries like "Which section has the financial tables?" or "Where are the figures?"

**Population rules:**

- Inspect `chunk_type` of all LDUs in the section.
- Map to a fixed enum: `tables`, `figures`, `equations`, `lists`, `other` (or extend as needed).
- `data_types_present` is the set of types present (e.g., `["tables", "figures"]`).
- If the section has child sections, optionally aggregate: a parent section's `data_types_present` may include types from descendants (e.g., "this section or its subsections contain tables"). Aggregation is configurable; leaf-only is simpler and often sufficient.

---

## 7. PageIndex Query Behavior

The **pageindex_query(topic)** operation is the entry point for PageIndex-first retrieval. Given a **topic string**, it returns the top-N most relevant sections **before** vector search, so the retrieval layer can restrict (or boost) chunk search to those sections.

### 7.1 pageindex_query(topic) — Contract

- **Name / concept:** `pageindex_query(topic)` (or equivalent: e.g. `query_pageindex(topic)`, PageIndex query).
- **Input:** `topic` — Natural language string (e.g., "capital expenditure projections for Q3", "risk factors"). Optional: `document_id`, `top_n` (default **3**).
- **Output:** List of **top-3** (default) section nodes most relevant to the topic. Each section includes at least: `id`, `title`, `page_start`, `page_end`, `summary` (if present), `ldu_ids`. Order: by relevance score descending.
- **Behavior:** Traverse the PageIndex tree; score each section by relevance to the topic using title, summary (if present), key_entities, data_types_present; rank and return the **top-3 sections**. This result is used **before** vector search to narrow the candidate LDU set (see §7.3).
- **Default top_n:** **3**. Configurable; Refinery Guide and Phase 3 acceptance use top-3 as the standard.

### 7.2 Query input (parameters)

- **topic** — Required. Natural language string describing what the user is looking for.
- **top_n** — Number of sections to return. **Default: 3.** Configurable.
- **document_id** — Which document's PageIndex to query (when the system has multiple documents).

### 7.3 Traversal and scoring

1. **Traverse the tree** — Visit each section node (root, then children recursively). Optionally prune: skip sections whose `page_start`/`page_end` or `summary` suggest irrelevance (implementation-defined).
2. **Score each section** — Relevance of the section to the topic. Signals:
   - **Title** — Lexical or semantic match (e.g., "Capital Budget" vs. "capital expenditure").
   - **Summary** — Semantic similarity between topic and summary. Use embeddings or keyword overlap.
   - **key_entities** — Overlap between topic and entities (e.g., "Q3" in topic, "Q3 2024" in entities).
   - **data_types_present** — If topic implies "table" (e.g., "revenue table"), boost sections with `tables`.
3. **Rank and return** — Return the top-N sections (default 3) by score. Each returned section includes: `id`, `title`, `page_start`, `page_end`, `summary`, `ldu_ids` so the retrieval layer can fetch only LDUs within those sections.

### 7.4 Integration with vector search

- **PageIndex-first flow:** Call `pageindex_query(topic)` → get top-3 (or top-N) sections → restrict vector search to LDUs whose `ldu_id` is in those sections' `ldu_ids` (or whose `parent_section` / `page_refs` fall within those sections) → return ranked chunks.
- **Fallback:** If PageIndex returns no relevant sections (e.g., topic is too generic), fall back to full-document vector search.
- **Hybrid:** Combine PageIndex scores with vector search scores (e.g., boost chunks from PageIndex-selected sections). Exact combination is implementation-defined.

### 7.5 Success criteria

- The Refinery Guide specifies: "Implement the PageIndex query: given a topic string, traverse the tree to return the top-3 most relevant sections before doing vector search. Measure retrieval precision with and without PageIndex traversal."
- PageIndex traversal should **outperform** naive vector search on section-specific queries (e.g., "What are the risk factors?" when the answer is in "Section 4: Risk Factors").

---

## 8. Storage & Serialization

### 8.1 Serialization requirements (mandatory)

- **Path:** PageIndex **must** be persisted to **`.refinery/pageindex/{document_id}.json`**. The path may be overridden by configuration (e.g. a base directory), but the canonical location for the Refinery pipeline is `.refinery/pageindex/{document_id}.json`. One file per document.
- **Format:** JSON. The full PageIndex (top-level + root Section tree) must be serializable to JSON and deserializable without loss. All section node fields required for query and retrieval (title, page_start, page_end, child_sections, key_entities, summary, data_types_present, ldu_ids) must be included in the persisted representation.
- **Round-trip:** Loading the file and re-serializing must produce an equivalent structure (same document_id, root, section hierarchy, and section fields). No runtime-only fields that cannot be persisted.
- **Encoding:** UTF-8. JSON keys and string values must be valid for JSON interchange.

### 8.2 Top-level persisted structure

The JSON file must contain at least:

- **document_id** — string; matches the document the PageIndex was built for.
- **page_count** — integer; total pages.
- **root** — object; the root Section (single tree root). Recursive structure: each section has title, page_start, page_end, child_sections (array of Section), key_entities, summary, data_types_present, ldu_ids.
- **built_at** (optional) — string; ISO 8601 timestamp when built.

Implementations may use `root_sections` (array of top-level sections) if the model uses an implicit root; the persisted file must still allow reconstruction of the tree and must satisfy the invariants below.

### 8.3 Invariants (persisted representation)

| Invariant | Requirement |
|-----------|-------------|
| **document_id** | Must match the document the PageIndex was built for. |
| **Root exists** | The tree has exactly one root Section (or equivalent top-level structure). |
| **Valid page range** | For every section, `page_start <= page_end`, and both are in `[1, page_count]`. |
| **Hierarchy consistency** | Child `page_start`/`page_end` within parent; siblings ordered by `page_start`. |
| **Idempotent load** | Loading the JSON and re-serializing must produce equivalent structure. |

### 8.4 Versioning and rebuild

- **built_at** (optional) — Timestamp enables "when was this built?" and stale detection.
- **Schema version** (optional) — If the Section schema evolves, a version field allows migration.
- **Rebuild trigger** — PageIndex should be rebuilt when LDUs change (e.g., re-chunking, re-extraction). The pipeline design must ensure PageIndex is built after chunking and before query-time use.

---

## 9. Failure Modes & Degradation

### 9.1 Weak or missing headings

**Scenario:** Document has no explicit headings, or headings are inconsistent (e.g., bold text not marked as headings, numbering missing).

**Behavior:**

- **Fallback to flat structure** — Create one section per page, or one section per N consecutive pages. Title: e.g., "Pages 1–5", "Pages 6–10". Summary and key_entities can still be generated from LDU content.
- **Fallback to root-only** — Single root section spanning the whole document. All LDUs belong to root. `child_sections` is empty. Topic traversal degrades to "whole document" but remains valid.
- **Heuristic titles** — If some structure is detectable (e.g., "Introduction" as first bold paragraph), create sections with heuristic titles. Log that headings were inferred.

**Principle:** Always produce a valid PageIndex. Never fail with "no headings, cannot build." Degrade to a flatter structure.

### 9.2 Noisy section detection

**Scenario:** Headings are over-detected (e.g., every paragraph starts with a number) or under-detected (nested structure missed).

**Behavior:**

- **Over-detection** — Apply a minimum section length (e.g., at least 2 LDUs or 1 page). Merge very short sections into the parent. Configurable threshold.
- **Under-detection** — Accept a flatter tree. Deep nesting is a nice-to-have; flat is acceptable. Log when expected hierarchy (e.g., "1.1" under "1") is not found.
- **Confidence flag** (optional) — Attach a `section_confidence` or `structure_quality` to the root or to sections when detection was heuristic. Enables downstream to prefer manual review or fallback retrieval for low-confidence documents.

### 9.3 Summarization failures

**Scenario:** LLM summarization fails (API error, rate limit, timeout) or returns low-quality output.

**Behavior:**

- **Null summary** — Leave `summary` null for affected sections. Section remains in tree; topic traversal falls back to title and key_entities.
- **Retry** — Optional retry with exponential backoff; if exhausted, proceed with null.
- **Log** — Record which sections failed summarization for debugging and cost analysis.

### 9.4 Empty or near-empty documents

**Scenario:** Document has no LDUs or very few (e.g., 1–2).

**Behavior:**

- **Minimal tree** — Root section with `page_start=1`, `page_end=page_count`, `child_sections=[]`, `summary=null`, `key_entities=[]`, `data_types_present=[]`. Valid but minimal.
- **No crash** — PageIndex Builder must not fail. Emit the minimal tree and log.

### 9.5 Degradation principle

When section detection or summarization is uncertain, **degrade gracefully** rather than fail. A flat or root-only PageIndex is still useful (it allows page-range filtering). The system must produce a valid, loadable PageIndex for every document that has at least one LDU. Log degradation reasons for tuning and improvement.

---

## 10. Open Questions

- **Exact scoring function** for PageIndex query: lexical vs. semantic, weights for title vs. summary vs. key_entities. To be tuned during Phase 3.
- **Aggregation of data_types_present** for parent sections: include descendants or leaf-only?
- **Entity extraction method:** NER library vs. LLM vs. keyword—cost-quality tradeoff. Pluggable design recommended.
- **Incremental rebuild:** When LDUs change for a subset of pages, can PageIndex be partially updated? Out of scope for initial spec; full rebuild is sufficient.

---

**Version:** 1.0  
**Spec status:** Spec only; implementation-agnostic. Ready for PageIndex Builder implementation.
