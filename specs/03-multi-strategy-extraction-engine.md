# Spec: Stage 2 – Multi-Strategy Extraction Engine

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Upstream:** [02 – Triage Agent & DocumentProfile](02-triage-agent-and-document-profile.md)  
**Constitution alignment:** Multi-strategy, cost-aware extraction (fast text → layout → VLM); spatial provenance on every extracted element; typed Pydantic contracts for ExtractedDocument; config-over-code for thresholds and routing.

---

## 1. Purpose

The Structure Extraction Layer balances **speed**, **cost**, and **fidelity** by offering three strategies instead of one. The goal is to extract structured content (text blocks, tables, figures) with page and bbox provenance while minimizing cost and avoiding under-extraction.

- **Strategy A (FastTextExtractor)** — Low cost, low latency. Suitable when the document has a reliable text layer and simple single-column layout. Uses text-stream extraction only; no layout or vision.

- **Strategy B (LayoutExtractor)** — Medium cost. Handles multi-column, tables, figures, and mixed layouts. Recovers structure (tables as JSON, figures with captions, reading order) that Strategy A cannot.

- **Strategy C (VisionExtractor)** — High cost. Used when text layer is absent (scanned) or prior strategies fail confidence gates. Passes page images to a vision-language model for extraction.

The extraction layer **must not** pass low-confidence output downstream (constitution: no “garbage in, hallucination out”). Strategy A must escalate to B when confidence is low; A and B may escalate to C when needed. All thresholds and routing rules are configurable (config-over-code).

---

## 2. Inputs

**Required inputs:**

- **DocumentProfile** — From Stage 1 (Triage Agent). Contains at least: `document_id`, `origin_type`, `layout_complexity`, `domain_hint`, `estimated_extraction_cost`, `triage_confidence_score`, `page_count`, `language`. Used by the Extraction Router to select initial strategy and escalation policy.

- **Document path (or equivalent)** — A reference to the raw document file (e.g. filesystem path, URI, or blob handle). The extraction layer must be able to read the document for the chosen strategy (e.g. PDF text layer for A, page images for C).

**Assumptions (what is available without extra work):**

- **Page count** — Known from DocumentProfile or derivable from the document.
- **MIME type or file extension** — Used to dispatch to PDF handling; current spec scope is PDF only.
- **Character stream and image metadata** — For PDFs, a library (e.g. pdfplumber, pymupdf) can provide per-page character counts, bounding boxes, image dimensions. Strategy A and confidence scoring depend on this.
- **Page images** — For Strategy C, each page can be rendered as an image (e.g. PNG) for VLM input.

**Pre-conditions:**

- DocumentProfile is valid and complete (all required fields present).
- Document file exists and is readable.
- No requirement that the document was seen before; extraction must work on unseen documents.

---

## 3. Outputs (ExtractedDocument – Logical Schema)

All three strategies must emit a **unified ExtractedDocument**. This is the normalized data contract for Stage 2. Every structural element carries **page** and **bbox** (constitution: spatial provenance non-negotiable). Implementations use typed models (e.g. Pydantic); this spec defines the logical structure only.

### 3.1 Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| **document_id** | string | Same as DocumentProfile.document_id; correlates with ledger and downstream stages. |
| **strategy_used** | enum | `fast_text` \| `layout` \| `vision` — Which strategy produced this output. |
| **page_count** | integer | Number of pages in the document. |
| **text_blocks** | list of TextBlock | Ordered sequence of text blocks (paragraphs, headings, list items). |
| **tables** | list of Table | Structured tables with headers and rows. |
| **figures** | list of Figure | Figures with optional captions. |
| **reading_order** | list of ReadingOrderEntry | Logical reading order of content (references to blocks, tables, figures by ID or index). |

### 3.2 TextBlock

| Field | Type | Description |
|-------|------|-------------|
| **id** | string | Unique identifier within the document (e.g. `block_001`). |
| **content** | string | Extracted text. |
| **page** | integer | 1-based page number. |
| **bbox** | object | Bounding box: `{x0, top, x1, bottom}` or equivalent (coordinates in points or normalized). |
| **block_type** | enum (optional) | `paragraph` \| `heading` \| `list_item` \| `caption` \| `other` — If detectable. |

### 3.3 Table

| Field | Type | Description |
|-------|------|-------------|
| **id** | string | Unique identifier within the document. |
| **page** | integer | 1-based page number. |
| **bbox** | object | Bounding box of the full table. |
| **headers** | list of string | Column headers (if present). |
| **rows** | list of list of string | Row data; each inner list is a row of cell values. |
| **num_rows** | integer | Number of data rows (excl. header). |
| **num_cols** | integer | Number of columns. |
| **caption** | string (optional) | Table caption, if present. |

### 3.4 Figure

| Field | Type | Description |
|-------|------|-------------|
| **id** | string | Unique identifier within the document. |
| **page** | integer | 1-based page number. |
| **bbox** | object | Bounding box of the figure. |
| **caption** | string (optional) | Figure caption; constitution requires captions to stay with figures. |
| **alt_text** | string (optional) | Alternative description, if available. |

### 3.5 ReadingOrderEntry

| Field | Type | Description |
|-------|------|-------------|
| **ref_type** | enum | `text_block` \| `table` \| `figure` |
| **ref_id** | string | ID of the referenced element. |
| **order** | integer | Position in reading order (0-based). |

**Invariants:**

- Every element in `text_blocks`, `tables`, `figures` has non-null `page` and `bbox`.
- `reading_order` is consistent with IDs in the referenced collections.
- Tables have at least one row; headers may be empty if not detectable.

---

## 4. Strategy A – FastTextExtractor (Low Cost)

### 4.1 When allowed

Strategy A is **permitted only** when:

- `origin_type = native_digital`
- `layout_complexity = single_column`

If either condition fails, the router must not select Strategy A. Even when permitted, Strategy A must compute a **confidence score** and **must not pass output downstream if confidence is below threshold**; it must escalate to Strategy B (or C if appropriate).

### 4.2 Confidence metrics

Strategy A must compute an **extraction confidence score** in [0, 1]. The score must incorporate at least:

- **Character count per page** — Pages with very low character count (e.g. &lt; 100) suggest scan or image-heavy content; lower confidence.
- **Character density** — Characters per unit page area. Low density with high image area suggests poor suitability for text-only extraction.
- **Image area ratio** — Fraction of page area occupied by images. Above a threshold (e.g. 50%) reduces confidence.
- **Font metadata presence** — Presence of font info indicates a real text layer; absence may indicate OCR or scan.

Exact formula and thresholds are configurable. The requirement is that the score reflects “how safe is it to use fast text for this document?”

### 4.3 Low-confidence behavior

- **Strategy A must not pass low-confidence output downstream.** If the computed confidence is below the configured threshold, Strategy A must **escalate** — i.e. hand off to Strategy B (or, if DocumentProfile indicates `needs_vision_model`, to Strategy C) without emitting its own ExtractedDocument.
- The extraction ledger must record that Strategy A was attempted, confidence was below threshold, and escalation occurred.
- No partial or “best effort” output from Strategy A when confidence is low. Escalation is mandatory.

---

## 5. Strategy B – LayoutExtractor (Medium Cost)

### 5.1 Coverage

Strategy B is used when:

- `layout_complexity` is `multi_column`, `table_heavy`, `figure_heavy`, or `mixed`
- OR `origin_type` is `mixed` (and not `scanned_image`)
- OR Strategy A escalated due to low confidence and DocumentProfile does not require vision

Strategy B handles documents where **layout and structure matter**: multi-column reading order, tables as structured data, figures with captions.

### 5.2 Structural elements to recover

Strategy B **must** produce:

- **Text blocks with bbox and page** — Paragraphs, headings, list items with spatial provenance. Order preserved or reconstructed.
- **Tables as structured JSON** — Headers and rows; cells not flattened into plain text. Tables must have `page`, `bbox`, `headers`, `rows`, and optional `caption`. No table may be emitted as a single undifferentiated text block.
- **Figures with captions** — Each figure has `page`, `bbox`, and `caption` (if present). Caption is stored with the figure (constitution: figure caption always with parent).
- **Reading order** — Logical order of blocks, tables, and figures across the document. Reading order must be explicitly represented (e.g. `reading_order` list) so downstream chunking respects document flow.

### 5.3 Quality expectations

- Multi-column documents: reading order must follow visual flow (e.g. left-to-right columns, top-to-bottom).
- Tables: header row identified when present; cell boundaries preserved; no merging of distinct cells.
- Figures: bbox covers the figure region; caption associated via `caption` field or adjacency in reading order.

Strategy B may use layout models (e.g. MinerU, Docling) or heuristics; implementation choice. Output must conform to the ExtractedDocument schema.

---

## 6. Strategy C – VisionExtractor (High Cost)

### 6.1 Triggers

Strategy C is used when:

- `origin_type = scanned_image`
- OR `estimated_extraction_cost = needs_vision_model`
- OR Strategy A or B produced output with confidence below threshold (escalation)
- OR handwriting is detected (if supported; otherwise treat as escalation path)

Strategy C is the fallback when text layer is absent or layout/text extraction fails confidence.

### 6.2 Input and prompts

- **Input:** Page images (e.g. PNG) for each page, or a subset if processing is partial.
- **Prompts:** Structured extraction prompts that request: (1) text blocks with approximate bbox, (2) tables as JSON with headers and rows, (3) figures with captions. Prompts must specify output format (e.g. JSON schema or schema-like description) so output can be normalized to ExtractedDocument.
- **Domain hint:** DocumentProfile.`domain_hint` may be used to tailor prompts (e.g. financial tables, legal clauses) for better extraction quality.

### 6.3 Quality expectations

- Vision extractor must produce ExtractedDocument conformant output: text_blocks, tables, figures, each with page and bbox.
- Bbox may be approximate (VLM-derived) but must be present. Page must be correct.
- Tables must be structured (headers + rows), not raw text dumps.
- Budget guard (see §8) applies; no single document may exceed the cost cap.

### 6.4 Model selection

- Model choice (e.g. GPT-4o-mini, Gemini Flash via OpenRouter) is configurable. Budget-aware selection is recommended (constitution: cost-aware).

---

## 7. Strategy Routing & Escalation Guard

### 7.1 Decision tree

1. **If** `origin_type = scanned_image` **OR** `estimated_extraction_cost = needs_vision_model`  
   → Start with Strategy C (no A/B attempt for scanned docs).

2. **Else if** `origin_type = native_digital` **AND** `layout_complexity = single_column`  
   → Try Strategy A first.  
   - **If** Strategy A confidence ≥ threshold → Emit Strategy A output.  
   - **Else** → Escalate to Strategy B. Do **not** emit Strategy A output.

3. **Else** (multi_column, table_heavy, figure_heavy, mixed layout, or mixed origin)  
   → Use Strategy B directly (no Strategy A attempt).

4. **If** Strategy B is used and produces output with confidence below threshold  
   → Escalate to Strategy C. Do **not** emit Strategy B output.

5. **If** Strategy C is used and still fails (e.g. budget cap, API error)  
   → See §10 (Failure Modes & Degradation Strategy).

### 7.2 Escalation guard (mandatory)

- **Strategy A must not pass low-confidence output downstream.** It must escalate to B (or C if profile requires vision). This is non-negotiable (constitution: no silent bad data).
- Strategy B, when used as escalation from A, may also have a confidence gate; if so, low confidence triggers escalation to C.
- Each escalation must be logged in the extraction ledger with reason (e.g. `confidence_below_threshold`).

### 7.3 Configurability

- Thresholds (e.g. minimum confidence for A/B to pass, character count per page, image area ratio) must be in configuration (extraction_rules.yaml or equivalent). No hardcoded magic numbers (constitution: config-over-code).

---

## 8. Budget Guard & Cost Logging

### 8.1 Token spend tracking

- **Per-document tracking:** Each extraction run must track estimated token usage (input + output) for any strategy that calls external APIs (notably Strategy C).
- **Cost estimate:** Map token counts to estimated cost using configured rates (e.g. $/1K tokens). Log the estimate in the extraction ledger.

### 8.2 Cap behavior

- **Per-document cap:** A configurable maximum cost (or token count) per document must exist. If a single document would exceed the cap:
  - Strategy C must **not** proceed for that document beyond the cap.
  - The system must either: (a) fail with a clear error and log, or (b) emit a partial ExtractedDocument with a flag indicating budget exhaustion, plus log. Exact behavior is configurable.
- **No silent over-spend:** The system must never exceed the cap without logging and explicit handling.

### 8.3 Strategy A and B

- Strategy A (text extraction) and Strategy B (layout models) may have minimal or zero API cost. If they use local models or libraries only, token tracking may be N/A; cost_estimate can be 0 or a small fixed value. The ledger must still record the strategy and processing time.

---

## 9. Extraction Ledger Requirements

Every extraction run must produce **one ledger entry**. Entries are appended to a machine-readable log (e.g. JSONL file). Required fields:

| Field | Type | Description |
|-------|------|-------------|
| **document_id** | string | Same as DocumentProfile.document_id. |
| **strategy_used** | enum | `fast_text` \| `layout` \| `vision` — Final strategy that produced output (or `escalation_failed` if none). |
| **confidence_score** | float | [0, 1] — Extraction confidence; for escalations, the score that triggered escalation. |
| **cost_estimate** | float | Estimated cost in configured currency/units; 0 if no API cost. |
| **processing_time_seconds** | float | Wall-clock time for the extraction run. |
| **timestamp** | string | ISO 8601 timestamp of completion. |
| **escalation_path** | list (optional) | Ordered list of strategies attempted before final (e.g. `["fast_text", "layout"]`). |
| **notes** | string (optional) | Free text (e.g. reason for escalation, budget cap hit). |

Ledger entries must be immutable once written. No deletion or modification of historical entries.

---

## 10. Failure Modes & Degradation Strategy

| Failure mode | Description | Required behavior |
|--------------|-------------|-------------------|
| **Strategy A confidence low** | Fast text unsuitable. | Escalate to B; do not emit A output. Log. |
| **Strategy B confidence low** | Layout extraction weak. | Escalate to C; do not emit B output. Log. |
| **Strategy C budget cap exceeded** | Document would exceed cost cap. | Halt C; log budget_exceeded; emit error or partial result with flag. Do not silently over-spend. |
| **Strategy C API failure** | VLM unavailable, timeout, rate limit. | Retry per configured policy (if any); if exhausted, fail with clear error. Log. Do not emit fake ExtractedDocument. |
| **All strategies exhausted** | A escalated to B, B escalated to C, C failed. | Emit a failure result (no ExtractedDocument) with explicit reason. Log full escalation path. Downstream stages must handle “no extraction” (e.g. skip chunking for that document). |
| **Corrupt or unreadable document** | PDF cannot be parsed. | Fail early; log; no ExtractedDocument. |
| **Partial success** | Some pages extracted, others failed (e.g. budget cap mid-document). | If partial output is emitted, it must be flagged (e.g. `partial=true`, `pages_missing=[...]`). Ledger must record partial status. |

**Degradation principle:** When in doubt, **fail explicitly** rather than emit low-quality output. The pipeline must not produce ExtractedDocuments that would cause “garbage in, hallucination out” downstream. Graceful degradation means: log, escalate, or fail with a clear signal—not silently pass bad data.

---

**Version:** 1.0  
**Spec status:** Ready for implementation; thresholds and exact formulas to be set in config during Phase 0/1.
