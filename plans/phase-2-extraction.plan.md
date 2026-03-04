# Phase 2: Multi-Strategy Extraction Engine — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Spec:** [03 – Multi-Strategy Extraction Engine](../specs/03-multi-strategy-extraction-engine.md).  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (ExtractedDocument §4.7, ExtractionLedgerEntry §9.1).  
**Target:** Phase 2 — Extract structured document content with confidence-gated escalation.

---

## 1. Goal

Extract **structured document content** (text blocks, tables, figures) with **page and bbox provenance** for every element, while balancing **speed**, **cost**, and **fidelity**. The extraction layer:

- Offers **three strategies** (fast text, layout-aware, vision) and a **router** that chooses the initial strategy from the DocumentProfile.
- Enforces a **confidence-gated escalation guard**: low-confidence output must not be passed downstream; the system escalates to the next strategy instead of emitting bad data (“garbage in, hallucination out”).
- Produces a **unified ExtractedDocument** from any strategy so Stage 3 (Chunking) and Stage 4 (PageIndex) consume a single schema.
- Logs every run to an **extraction ledger** (strategy used, confidence, cost, escalation path) for audit and tuning.

Phase 2 delivers the structure extraction layer that makes the refinery capable of handling native digital, multi-column, table-heavy, and scanned documents through a single, typed contract.

---

## 2. Strategy Interface

### 2.1 BaseExtractor (conceptual interface)

All extractors implement the same contract so the router can delegate and escalate uniformly.

**Signature (conceptual):**

- **Input:** `doc_path` (path or URI to the document), `profile` (DocumentProfile from Stage 1).
- **Output:** Either a successful result or an escalation/failure signal.
  - **Success:** `ExtractedDocument` plus a **confidence score** in [0, 1]. The ExtractedDocument must include `strategy_used` and `strategy_confidence` (or equivalent) per models spec.
  - **Escalation / failure:** No ExtractedDocument; instead a structured result indicating “confidence below threshold” or “error” (e.g. exception or result type with reason). The router uses this to try the next strategy or fail.

**Contract:**

- Every successful return must conform to the **ExtractedDocument** schema (document_id, text_blocks, tables, figures, reading_order, strategy_used, strategy_confidence; every element with page and bbox). Invariants in spec 03 and spec 07 must hold.
- Confidence score must reflect “how safe is it to use this extraction downstream?” — e.g. for Strategy A: character count, density, image area, font metadata; for Strategy B/C: extraction completeness or model-specific signals.
- If the extractor cannot produce valid output (e.g. corrupt PDF), it must not return an ExtractedDocument; it must signal error or escalation.

**Design note:** Implementation may use a protocol, abstract base class, or dependency-injected callable. The plan treats “BaseExtractor” as the conceptual interface name; concrete implementations are FastTextExtractor, LayoutExtractor, VisionExtractor.

---

## 3. Strategies

### 3.1 FastTextExtractor (Strategy A — low cost)

**Role:** Text-stream extraction only; no layout or vision. Suitable when the document has a reliable text layer and simple single-column layout.

**When allowed:** Router may call Strategy A **only** when `profile.origin_type == native_digital` and `profile.layout_complexity == single_column`. If either condition fails, the router must not select Strategy A.

**Tool:** pdfplumber or pymupdf. Extract text and character/word/line objects with bbox and page. No table structure detection; tables may appear as flattened text. Reading order is typically default (e.g. page order, top-to-bottom).

**Output normalization:** Map raw extraction to ExtractedDocument: text_blocks (with id, content, page, bbox, optional block_type), tables (if any — may be empty or heuristic grouping), figures (if any — may be empty), reading_order (e.g. by page and vertical position). Every element must have non-null page and bbox (constitution: spatial provenance non-negotiable).

**Confidence metrics (required):** Strategy A must compute an extraction confidence score in [0, 1] using at least:
- Character count per page (e.g. very low → lower confidence).
- Character density (chars per page area).
- Image area ratio (fraction of page occupied by images; high with low text → lower confidence).
- Font metadata presence (real text layer vs. absent/sparse).

Thresholds (e.g. min character count per page, max image area ratio for “confident”) are configurable (extraction_rules.yaml or equivalent). The score must reflect “how safe is it to use fast text for this document?”

**Low-confidence behavior:** If confidence is below the configured threshold, Strategy A **must not** return an ExtractedDocument. It must signal “escalate” (e.g. return a result type that tells the router to try Strategy B or C). No partial or best-effort output when below threshold; escalation is mandatory. The ledger must record that Strategy A was attempted and escalation occurred.

---

### 3.2 LayoutExtractor (Strategy B — medium cost)

**Role:** Recover structure that Strategy A cannot: multi-column reading order, tables as structured JSON (headers + rows), figures with captions. Uses a layout model or heuristic (MinerU, Docling, or equivalent).

**When used:** Router selects Strategy B when:
- `layout_complexity` is `multi_column`, `table_heavy`, `figure_heavy`, or `mixed`, or
- `origin_type` is `mixed` (and not `scanned_image`), or
- Strategy A was tried and escalated due to low confidence and the profile does not require vision.

**Adapter / output normalization:** The layout tool (Docling, MinerU) has its own document representation. Phase 2 must implement an **adapter** that normalizes that representation to the internal **ExtractedDocument** schema:
- Text blocks with id, content, page, bbox, optional block_type.
- Tables with id, page, bbox, headers, rows, num_rows, num_cols, optional caption.
- Figures with id, page, bbox, optional caption, optional alt_text.
- Reading order: explicit list of ref_type (text_block | table | figure), ref_id, order.

All thresholds and tool-specific options (e.g. Docling/MinerU config) are configurable. Output must satisfy ExtractedDocument invariants (every element has page and bbox; reading_order consistent with IDs).

**Confidence (optional but recommended):** Strategy B may expose a confidence score (e.g. from layout model, or heuristic based on table/figure coverage). If present, the router can use it for B→C escalation when below threshold.

---

### 3.3 VisionExtractor (Strategy C — high cost)

**Role:** Fallback when the text layer is absent (scanned) or when Strategy A/B fail confidence. Passes page images to a vision-language model (VLM) for extraction.

**When used:** Router selects Strategy C when:
- `origin_type == scanned_image` or `estimated_extraction_cost == needs_vision_model`, or
- Strategy A or B was tried and produced output with confidence below threshold (escalation).

**Design (implementation or stub):** Phase 2 may implement a **full** VisionExtractor (page render → VLM API → structured output → normalize to ExtractedDocument) or a **stub** that:
- Accepts the same interface (doc_path, profile) and returns a clear “not implemented” or “stub” result (no ExtractedDocument, or a minimal placeholder with a flag), and
- Leaves budget guard hooks and ledger fields in place so that when Strategy C is implemented later, ledger and router behavior already support it.

If designing only (stub initially): define the **input** (page images, prompt template, domain_hint for prompt tailoring), **output** (VLM response normalized to ExtractedDocument: text_blocks, tables, figures with page and bbox; bbox may be approximate), and **budget guard** (per-document token/cost cap; when exceeded, halt and log). The stub need not call any API; it must only satisfy the router’s expectation (e.g. return an error or “stub” so the router can record strategy_used and escalation_path).

**Budget guard:** When Strategy C is implemented, track token usage (input + output) per document, map to cost (e.g. $/1K tokens), and enforce a configurable per-document cap. If the cap would be exceeded, do not proceed beyond the cap; log and either fail or emit partial result with a flag (per spec §8).

---

## 4. Router

### 4.1 ExtractionRouter

The **ExtractionRouter** is the single entry point for extraction. It:

1. **Reads DocumentProfile** (e.g. from `.refinery/profiles/{document_id}.json` or passed in) and the document path.
2. **Selects the initial strategy** using the decision tree below.
3. **Calls the chosen extractor** (BaseExtractor interface): `extract(doc_path, profile)`.
4. **Evaluates the result:** If the extractor returns an ExtractedDocument and confidence ≥ threshold, emit that and log. If the extractor signals “escalate” (confidence below threshold or error), **do not** emit that extractor’s output; try the next strategy in the escalation path. Repeat until a strategy returns acceptable output or all strategies are exhausted.
5. **Writes one ExtractionLedgerEntry** per run (see §5) and appends to the ledger JSONL.
6. **Invokes budget guard hooks** when calling Strategy C (e.g. check cap before/after; if over cap, do not emit and log).

### 4.2 Decision tree (initial strategy + escalation)

1. **If** `profile.origin_type == scanned_image` **OR** `profile.estimated_extraction_cost == needs_vision_model`  
   → Start with **Strategy C**. Do not try A or B for scanned docs.

2. **Else if** `profile.origin_type == native_digital` **AND** `profile.layout_complexity == single_column`  
   → Try **Strategy A** first.  
   - If Strategy A returns ExtractedDocument and confidence ≥ threshold → emit A output, log, done.  
   - Else (escalation) → do **not** emit A output; try **Strategy B**.

3. **Else** (multi_column, table_heavy, figure_heavy, mixed layout, or mixed origin)  
   → Use **Strategy B** directly (no Strategy A attempt).

4. **If** Strategy B was used and returns output with confidence below threshold  
   → Do **not** emit B output; escalate to **Strategy C**.

5. **If** Strategy C is used and fails (e.g. budget cap, API error, or stub “not implemented”)  
   → Emit a **failure result** (no ExtractedDocument) with explicit reason; log full escalation path. Downstream (e.g. Chunking) must handle “no extraction” (e.g. skip that document).

All thresholds (e.g. minimum confidence for A and B to pass) are in configuration. No hardcoded magic numbers.

### 4.3 Escalation guard (mandatory)

- **Strategy A must not pass low-confidence output downstream.** If confidence &lt; threshold, the router must escalate to B (or C if profile requires vision) and must **not** emit Strategy A’s output. This is non-negotiable (constitution).
- Strategy B, when used after A or as initial strategy, may have a confidence gate; if so, low confidence triggers escalation to C and the router must not emit B’s output.
- Each escalation must be recorded in the ledger (e.g. `escalation_chain` and `notes`).

### 4.4 Budget guard hooks

- **Before Strategy C:** If a per-document budget cap is configured, check whether running Strategy C would exceed it (e.g. estimated tokens × cost per token). If so, do not call Strategy C; fail or emit “budget exceeded” and log.
- **During/after Strategy C:** Track actual token usage and cost; append to ledger. If the cap is hit mid-document, behavior is configurable (halt and partial result with flag, or fail). No silent over-spend.
- **Hooks:** The router should call into a small “budget guard” module or callback so that cap logic and token counting are in one place and testable. Strategy A and B may report cost_estimate 0 or a fixed value; Strategy C reports real or estimated cost.

---

## 5. Ledger

### 5.1 ExtractionLedgerEntry fields

Every extraction run produces **one** ledger entry. Fields align with [spec 07 §9.1](../specs/07-models-schemas-spec.md) and spec 03 §9. Required (or recommended) fields:

| Field | Type | Description |
|-------|------|-------------|
| **document_id** | string | Same as DocumentProfile.document_id. |
| **strategy_used** | string | `fast_text` \| `layout` \| `vision` — Final strategy that produced output; or a sentinel (e.g. `escalation_failed`) if no strategy succeeded. |
| **origin_type** | string | From profile; for audit. |
| **layout_complexity** | string | From profile; for audit. |
| **start_time** / **end_time** | datetime | Run timing. |
| **processing_time_ms** (or **processing_time_seconds**) | number | Wall-clock duration. |
| **confidence_score** | float | [0, 1] — Extraction confidence of the final output; or the score that triggered escalation if no output. |
| **cost_estimate_usd** (or **cost_estimate**) | float | Estimated cost; 0 for A/B if no API. |
| **token_usage_prompt** / **token_usage_completion** | int, optional | For Strategy C; for cost and budget tracking. |
| **escalation_chain** | list of string | Ordered list of strategies attempted (e.g. `["fast_text", "layout"]`). Final strategy must match last element. |
| **notes** | string, optional | Free text (e.g. reason for escalation, budget cap hit, “confidence_below_threshold”). |

**Invariants:** `end_time >= start_time`. `strategy_used` must equal the last element of `escalation_chain` when a strategy succeeded; when all fail, `strategy_used` may be `escalation_failed` and `escalation_chain` lists all attempted strategies.

### 5.2 JSONL logging

- **Path:** `.refinery/extraction_ledger.jsonl` (or configurable equivalent).
- **Format:** One JSON object per line (JSONL). Each line is a serialized ExtractionLedgerEntry (or a minimal superset). Datetimes as ISO 8601 strings.
- **Append-only:** Entries are immutable once written. No deletion or modification of historical entries.
- **Idempotence:** Re-running extraction for the same document adds a **new** entry (each run is one row); no overwrite of previous rows.

---

## 6. Acceptance Checks

### 6.1 Unit tests for confidence scoring

- **Strategy A:** Given a PDF (or fixture) with high character count and low image area, the FastTextExtractor returns a confidence score above the configured threshold. Given a PDF (or fixture) with very low character count or high image area, the confidence score is below threshold (or a test that changing the fixture/config changes pass/fail).
- **Strategy A formula:** At least one test that documents or asserts that the score incorporates character count, character density, image area ratio, and font metadata (e.g. mock or fixture where one signal is bad and score drops).
- **Strategy B (if confidence implemented):** If LayoutExtractor exposes confidence, a test that exercises it (e.g. returns a value in [0, 1] or triggers escalation when below threshold).

### 6.2 Router escalation behavior (at least one low-confidence scenario)

- **Scenario:** A document that is permitted for Strategy A (native_digital, single_column) but produces low confidence (e.g. low character count or high image area). The router must **not** emit Strategy A’s ExtractedDocument; it must escalate to Strategy B (or C if profile requires vision). After the run, the ledger must contain an entry with `escalation_chain` including `fast_text` and the final strategy (e.g. `layout`), and `notes` or similar indicating escalation (e.g. “confidence_below_threshold”).
- **Evidence:** A test or scripted run: (1) use a profile and document that trigger low Strategy A confidence; (2) run the router; (3) assert that the emitted result is **not** from Strategy A (e.g. strategy_used is layout or vision); (4) assert the ledger entry has escalation_chain and correct strategy_used.

### 6.3 ExtractedDocument invariants

- For at least one successful extraction (Strategy A or B), the output ExtractedDocument has: non-empty document_id; text_blocks, tables, figures (or empty lists) with every element having non-null page and bbox; reading_order consistent with IDs; strategy_used and strategy_confidence set. A test or manual check validates these invariants (or the model’s validators pass).

### 6.4 Ledger presence and shape

- After at least one full extraction run (success or failure), a ledger file exists at `.refinery/extraction_ledger.jsonl` (or configured path) with at least one line. The line parses as JSON and contains document_id, strategy_used, confidence_score, processing_time, and escalation_chain (or equivalent). No requirement for cost/token fields if Strategy C is stubbed.

### 6.5 Configurability

- Confidence thresholds (e.g. fast_text_confidence_threshold, layout_confidence_threshold) are loaded from configuration. A test or manual run that changes the threshold and re-runs extraction shows different behavior (e.g. same document passes with higher threshold and escalates with lower threshold).

---

**Version:** 1.0  
**Plan status:** Plan only; no code. Implementation follows this plan and spec 03; models follow spec 07.
