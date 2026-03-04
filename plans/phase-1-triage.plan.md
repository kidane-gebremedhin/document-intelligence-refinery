# Phase 1: Triage Agent & Document Profiling — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Spec:** [02 – Triage Agent & DocumentProfile](../specs/02-triage-agent-and-document-profile.md).  
**Target:** Phase 1 — Build the classification layer that makes all downstream decisions intelligent.

---

## 1. Goal

Produce a **DocumentProfile** per document that **drives extraction routing**. The profile is the sole input to the Extraction Router (Stage 2). It must:

- **Select initial strategy:** e.g. `origin_type=native_digital` and `layout_complexity=single_column` → try Strategy A; `table_heavy` or `multi_column` → Strategy B; `scanned_image` → Strategy C.
- **Set escalation policy:** `estimated_extraction_cost=needs_vision_model` means the extractor is prepared to use Strategy C; `fast_text_sufficient` means Strategy A with a confidence gate and optional escalation to B.
- **Tune downstream:** `domain_hint` (financial, legal, technical, medical, general) drives prompt/schema choice in extraction and query stages.

Without triage, every document would be treated as worst-case (vision model), which is cost-prohibitive. Phase 1 delivers the classification layer so the pipeline can be cost-aware and correct-by-construction for strategy selection.

---

## 2. Inputs / Outputs

### 2.1 Inputs

| Input | Type | Description |
|-------|------|-------------|
| **PDF path** | string (path or URI) | Path to the document file. Triage operates on one document per invocation. |
| **Basic metadata** (optional) | dict or equivalent | Optional: filename, MIME type, file size. Not required for classification; used for `document_id` derivation or display. |

**Pre-conditions:**

- File exists and is readable.
- Format is PDF (primary target). Pipeline may later extend to Word/Excel; for Phase 1, PDF only.
- No requirement that the document was seen before; triage uses only heuristics and configurable thresholds.

### 2.2 Outputs

| Output | Type | Description |
|--------|------|-------------|
| **DocumentProfile** | structured record (e.g. Pydantic model) | One profile per document. All classification dimensions and invariants per spec. |
| **Profile JSON** | file | Persisted profile at a well-defined path (see §4). |
| **Confidence scores** | part of profile | `triage_confidence_score` in [0, 1]; optionally per-dimension or in metadata. Used for logging and downstream escalation. |

**DocumentProfile fields (minimal set for routing):**

- `document_id`, `origin_type`, `layout_complexity`, `language`, `language_confidence`, `domain_hint`, `estimated_extraction_cost`, `triage_confidence_score`, `page_count`, optional `notes`.

**Invariants (must hold on every emitted profile):**

- `origin_type = scanned_image` → `estimated_extraction_cost = needs_vision_model`.
- `layout_complexity` in `table_heavy`, `multi_column`, `figure_heavy`, `mixed` → `estimated_extraction_cost` at least `needs_layout_model`.
- Only when `origin_type = native_digital` and `layout_complexity = single_column` (and other guards) → `estimated_extraction_cost = fast_text_sufficient`.
- `triage_confidence_score` reflects ambiguity (e.g. borderline thresholds or conflicting signals → lower score).

---

## 3. Classification Dimensions

### 3.1 origin_type detection signals

**Enum:** `native_digital` | `scanned_image` | `mixed` | `form_fillable`.

**Signals to use (from spec and Refinery Guide):**

- **Character density** — Characters per page (or per unit page area). Native digital: high; scanned (no OCR): zero or near-zero. Threshold: e.g. minimum character count per page for “digital”; from Phase 0 / config.
- **Whitespace ratio** — Fraction of page area that is empty or low-density. High ratio may indicate image-only pages.
- **Image area ratio** — Fraction of page area occupied by embedded images. High image area with low character count → scan or figure-heavy. Threshold: e.g. max image area ratio for “digital” (Refinery Guide: “images < 50% of page area” as example).
- **Font metadata presence** — PDF reports font info for text. Absence or very sparse font data can indicate scanned/OCR content.
- **Page-level aggregation** — “Mixed” when some pages have sufficient character stream and others do not. Compute signals per page; aggregate (e.g. fraction of pages above character-count threshold).
- **Form_fillable** — Detect AcroForm / fillable form fields in PDF; can coexist with other origin types.

**Rules:**

- All thresholds configurable (extraction_rules.yaml or equivalent). No hardcoded magic numbers.
- Conflicting signals (e.g. font suggests digital but character count zero): resolve by defined rule order (e.g. “all pages zero chars → scanned_image”), emit valid profile, set low `triage_confidence_score` and optional `notes`.

### 3.2 layout_complexity signals

**Enum:** `single_column` | `multi_column` | `table_heavy` | `figure_heavy` | `mixed`.

**Signals to use:**

- **Column count** — Heuristic from character bbox clustering or line positions. Two or more columns → `multi_column`.
- **Table presence** — (a) Explicit table detection (layout model or bbox grouping), or (b) proxy: regions with high density of short, aligned lines. Output: table area ratio and/or table region count per page. Compare to config thresholds for `table_heavy` (e.g. table area ratio > X%, or > N table regions per page).
- **Figure/image area** — Same image area ratio as for origin_type; compare to threshold for `figure_heavy` (e.g. non-text area > Y%).
- **Dominance rule** — If both table and figure ratios high, or neither dominates → `mixed`.

**Thresholds (config):**

- table_heavy: e.g. table area ratio > 25% or > 2 table regions per page (spec suggests; exact in config).
- figure_heavy: e.g. image area > 40% (exact in config).

### 3.3 domain_hint classifier rules

**Enum:** `financial` | `legal` | `technical` | `medical` | `general`.

**Approach (minimum):**

- **Keyword-based:** Per-domain keyword sets (e.g. financial: revenue, balance sheet, fiscal, audit, expenditure; legal: whereas, hereby, clause, agreement, court; technical: implementation, assessment, methodology, findings; medical: patient, diagnosis, treatment, clinical). Sample text from document (e.g. first N pages or full text if available). Score by presence/frequency; assign domain with highest score if above confidence threshold, else `general`.
- **Pluggable:** Implement as a replaceable strategy so a VLM or other service can be swapped in later without changing DocumentProfile schema.
- **Configurable:** Keyword sets and confidence cutoff in config.

### 3.4 estimated_extraction_cost (derived)

**Enum:** `fast_text_sufficient` | `needs_layout_model` | `needs_vision_model`.

**Mapping (required logic):**

- `origin_type = scanned_image` → `needs_vision_model`.
- `origin_type = mixed` → at least `needs_layout_model`; may be `needs_vision_model` if text-layer confidence is low.
- `layout_complexity` in `table_heavy`, `multi_column`, `figure_heavy`, `mixed` → at least `needs_layout_model`.
- Only when `origin_type = native_digital` and `layout_complexity = single_column` (and any other guards) → `fast_text_sufficient`.

### 3.5 triage_confidence_score

- Single score in [0, 1] reflecting how unambiguous the classification is.
- Lower when: signals conflict, values near threshold boundaries, or domain_hint = general due to weak keyword match.
- Implementation may combine per-dimension confidences (min, product, or weighted average). Formula is implementation-defined; score must be stored and used for logging and optional downstream escalation.

### 3.6 language and language_confidence (optional for Phase 1)

- **language:** ISO 639-1 code or `unknown`.
- **language_confidence:** [0, 1].
- If language detection is deferred: emit `language=unknown`, `language_confidence=0.0`. Spec allows this.

---

## 4. Integration Points

### 4.1 Where profile JSON is saved

- **Path pattern:** `.refinery/profiles/{document_id}.json` (Refinery Guide and spec). `document_id` is a stable identifier (e.g. hash of path or content).
- **Format:** JSON serialization of DocumentProfile. One file per document.
- **Idempotence:** Re-running triage on the same document overwrites the profile (or versioned path if schema supports it).
- **Directory:** Ensure `.refinery/profiles/` exists (or equivalent per project convention); creation is part of Phase 1 setup.

### 4.2 How the downstream router consumes the profile

- **Extraction Router (Stage 2)** reads the profile by `document_id`: load `.refinery/profiles/{document_id}.json` (or equivalent) and deserialize into DocumentProfile.
- **Consumed fields for routing:** `origin_type`, `layout_complexity`, `estimated_extraction_cost`. Optional: `domain_hint` (for extraction prompts), `triage_confidence_score` (for escalation policy), `page_count`.
- **Contract:** Router expects all required fields to be present and invariants to hold. No partial or invalid profile; triage must emit a valid profile or an explicit error (no profile file).
- **Failure:** If profile is missing for a document, the router should treat as error or “triage not run” and not guess strategy.

---

## 5. Acceptance Checks

### 5.1 Unit tests

- **origin_type:** Given a known document (or fixture) that is native digital, scanned, or mixed, the triage agent produces the expected `origin_type`. At least one test per value (or per detectable value) with a clear fixture or mock.
- **layout_complexity:** Given a known document that is single-column, multi-column, or table-heavy, the triage agent produces the expected `layout_complexity`. At least one test per targeted value.
- **domain_hint:** Given text or a minimal PDF with domain-specific keywords (e.g. financial terms), the triage agent produces the expected `domain_hint`. At least one test per domain (or a subset) and one for `general` when keywords are absent or weak.
- **Invariants:** Tests that when `origin_type=scanned_image`, `estimated_extraction_cost=needs_vision_model`; when `layout_complexity` is table_heavy/multi_column, cost is at least needs_layout_model; when native_digital and single_column, cost can be fast_text_sufficient.
- **Confidence:** Test that ambiguous or conflicting signals produce a lower `triage_confidence_score` (or a note).
- **Error handling:** Test that unreadable file, empty PDF, or corrupt input does not produce a normal profile; error or sentinel is emitted and optionally logged.

### 5.2 Sample run producing profiles for at least a few documents

- Run the Triage Agent on **at least three documents** (ideally spanning different classes: e.g. one native digital, one scanned, one table-heavy or multi-column).
- **Evidence:** For each document, a profile JSON exists at `.refinery/profiles/{document_id}.json` (or configured path).
- **Evidence:** Each profile contains all required fields and satisfies invariants. `triage_confidence_score` is present; `estimated_extraction_cost` is consistent with `origin_type` and `layout_complexity`.
- **Evidence:** Manual or scripted check: document class (A–D) aligns with expected profile (e.g. Class B → scanned_image, needs_vision_model; Class A → multi_column or table_heavy, needs_layout_model). Exact alignment criteria can be “reasonable match” if strict labels are not yet available.

### 5.3 Configurability

- Thresholds (character count, image area ratio, table/figure ratios, domain keywords) are loaded from configuration (e.g. extraction_rules.yaml). No hardcoded thresholds in code. Evidence: changing a threshold in config and re-running triage changes the outcome where applicable.

### 5.4 Logging

- Every triage run is logged with at least: document_id, timestamp, outcome (success/error), and the emitted DocumentProfile (or error reason). Logs are machine-readable (e.g. JSON lines). Evidence: log file or stream contains the required fields for at least one run.

---

**Version:** 1.0  
**Plan status:** Plan only; no code. Implementation follows this plan and spec 02.
