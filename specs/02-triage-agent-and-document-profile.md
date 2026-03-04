# Spec: Stage 1 – Triage Agent & DocumentProfile

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Constitution alignment:** DocumentProfile is a typed data contract (Pydantic). Triage output drives multi-strategy, cost-aware extraction (Strategy A/B/C selection). All thresholds and routing rules are config-over-code (extraction_rules.yaml or equivalent).

---

## 1. Purpose

We classify documents **before** extraction so the pipeline can choose the right strategy and avoid over-spending (e.g. running a VLM on a clean native PDF) or under-extracting (e.g. running fast text on a scanned form). The Triage Agent is the single place that answers: “What kind of document is this, and what extraction cost tier should we assume?”

The **DocumentProfile** produced by triage is the **sole input** to the Extraction Router (Stage 2). The router uses it to:

- **Select initial strategy:** e.g. `origin_type=native_digital` and `layout_complexity=single_column` → try Strategy A (fast text); `table_heavy` or `multi_column` → Strategy B (layout-aware); `scanned_image` or `mixed` → Strategy B or C depending on policy.
- **Set escalation policy:** `estimated_extraction_cost=needs_vision_model` implies the extractor should be prepared to escalate to Strategy C; `fast_text_sufficient` implies Strategy A with a confidence gate and optional escalation to B.
- **Tune extraction prompts:** `domain_hint` (financial, legal, technical, medical, general) can drive prompt or schema choice in downstream stages.

Without triage, every document would need to be treated as “worst case” (vision model), which is cost-prohibitive at scale. Triage makes the 48-hour, cost-aware refinery possible.

---

## 2. Inputs & Pre-Conditions

**Inputs at this stage:**

- **Single document** to be classified. The Triage Agent operates on one document per invocation; batch orchestration is outside this stage.
- **Document format:** The primary target is **PDF** (native digital or image-based). The spec assumes the pipeline can open the file and, for PDFs, access at least:
  - Page count.
  - Per-page or whole-document signals that can be derived from a PDF library (e.g. character stream presence, character/word counts, bounding boxes, embedded image dimensions). Specifics of which library (e.g. pdfplumber, pymupdf) are implementation detail; the requirement is that **character-level or text-layer metadata** and **image/vector object metadata** are available for heuristic computation.
- **Document classes (reference corpus):** The agent must correctly triage the four system-spec classes:
  - **Class A:** Native digital PDF, multi-column, financial tables (→ expect `native_digital` or `mixed`, `multi_column` or `table_heavy`, `financial`).
  - **Class B:** Scanned PDF, no character stream (→ expect `scanned_image`, `needs_vision_model`).
  - **Class C:** Mixed text/tables, hierarchical sections (→ expect `native_digital` or `mixed`, `multi_column` or `mixed`, `technical`).
  - **Class D:** Table-heavy, numerical (→ expect `native_digital` or `mixed`, `table_heavy`, `financial` or `general`).

**Pre-conditions:**

- File is readable and recognized as PDF (or a supported type if the system later extends to Word/Excel; for this spec, PDF only).
- No requirement that the document has been seen before; triage must work on unseen documents using only the heuristics and thresholds defined below.
- Thresholds and enum definitions are **configurable** (config-over-code); default values are specified in Open Questions.

---

## 3. Outputs (DocumentProfile Schema)

The Triage Agent emits a **DocumentProfile**: one structured record per document. It is the data contract for Stage 1. All fields are required unless marked optional. Implementations must use a typed model (e.g. Pydantic) and persist it (e.g. as JSON) for downstream stages and audit.

| Field | Type | Allowed values / constraints | Description |
|-------|------|-----------------------------|-------------|
| **document_id** | string | Non-empty, stable identifier for this document (e.g. hash of path or content) | Used for storage keys and ledger correlation. |
| **origin_type** | enum | `native_digital` \| `scanned_image` \| `mixed` \| `form_fillable` | How the document was produced: digital text layer vs. scan vs. mix vs. fillable form. |
| **layout_complexity** | enum | `single_column` \| `multi_column` \| `table_heavy` \| `figure_heavy` \| `mixed` | Structural complexity of the layout; drives Strategy A vs. B. |
| **language** | string | ISO 639-1 code (e.g. `en`, `am`) or `unknown` | Primary language of the document. |
| **language_confidence** | float | [0.0, 1.0] | Confidence in the language detection. |
| **domain_hint** | enum | `financial` \| `legal` \| `technical` \| `medical` \| `general` | Domain for prompt/schema selection; not for access control. |
| **estimated_extraction_cost** | enum | `fast_text_sufficient` \| `needs_layout_model` \| `needs_vision_model` | Recommended extraction tier; used by Extraction Router. |
| **triage_confidence_score** | float | [0.0, 1.0] | Aggregate confidence in this classification; used for logging and optional escalation. |
| **page_count** | integer | ≥ 1 | Number of pages; may be used by downstream stages. |
| **notes** | string (optional) | Free text | Optional human-readable note (e.g. “conflicting signals: defaulted to mixed”). |

**Invariants (business rules):**

- If `origin_type = scanned_image` then `estimated_extraction_cost` must be `needs_vision_model`.
- If `layout_complexity` is `table_heavy` or `multi_column`, then `estimated_extraction_cost` must not be `fast_text_sufficient` (at least `needs_layout_model`).
- `triage_confidence_score` must reflect ambiguity: e.g. conflicting signals or borderline thresholds should produce a lower score.

---

## 4. Classification Dimensions & Definitions

Exact definitions so that “table_heavy” and every other value are unambiguous.

### 4.1 origin_type

| Value | Definition |
|-------|------------|
| **native_digital** | Document has a reliable text layer (character stream) and was authored digitally. Typical: PDFs generated from Word/LaTeX/InDesign. Heuristic: character density and font metadata indicate text is primary; image area is not dominant. |
| **scanned_image** | Document is primarily raster images (scanned pages). No or negligible character stream; text would require OCR/VLM. Heuristic: no meaningful character count per page, or character count below a configured minimum. |
| **mixed** | Some pages or regions have a text layer, others are image-only. Heuristic: fraction of pages with sufficient character stream is between two thresholds (e.g. not all pages digital, not all scanned). |
| **form_fillable** | PDF contains fillable form fields (AcroForm). May coexist with native_digital or scanned_image. Used for routing or prompt choice (e.g. form-specific extraction). Detection: presence of form field metadata in the PDF. |

### 4.2 layout_complexity

| Value | Definition |
|-------|------------|
| **single_column** | Predominant layout is one main text column per page. No or few tables; figures are not the dominant content. Suitable for fast text extraction if origin is digital. |
| **multi_column** | Two or more text columns per page (e.g. reports, newsletters). Reading order and structure matter; fast text often gets order wrong. Requires layout-aware extraction. |
| **table_heavy** | Tables occupy a significant share of page area or count. “Significant” is defined by configurable thresholds: e.g. **table area ratio** (sum of table bbox areas / page area) above X% **or** number of table regions per page above N. Tables must be extracted as structure, not plain text. |
| **figure_heavy** | Figures, charts, or images occupy a significant share of page area (e.g. above Y% of page area). Captions and structure around figures matter; may need layout or vision. |
| **mixed** | No single category dominates: e.g. some pages single-column, others multi-column or with many tables. Or combination of table_heavy and figure_heavy. Use when heuristics do not clearly favor one of the above. |

**Operational thresholds (to be set in config):**

- **table_heavy:** e.g. table area ratio &gt; 25% of page area (averaged over pages), OR &gt; 2 table regions per page on average. Exact numbers are Open Questions.
- **figure_heavy:** e.g. non-text (image/figure) area &gt; 40% of page area on average. Exact number is Open Question.

### 4.3 language and language_confidence

- **language:** ISO 639-1 two-letter code, or `unknown` if detection is not run or fails.
- **language_confidence:** Confidence of the detector in [0, 1]. Enables downstream to prefer high-confidence language for prompts.

### 4.4 domain_hint

| Value | Definition |
|-------|------------|
| **financial** | Content suggests financial reports, statements, tax, or fiscal data (e.g. keywords: revenue, balance sheet, fiscal, audit, expenditure). |
| **legal** | Content suggests legal or regulatory (e.g. keywords: whereas, hereby, clause, agreement, court). |
| **technical** | Content suggests technical reports, assessments, or manuals (e.g. keywords: implementation, assessment, methodology, findings). |
| **medical** | Content suggests clinical or health (e.g. keywords: patient, diagnosis, treatment, clinical). |
| **general** | None of the above, or confidence in domain detection below threshold. Default when keyword match is weak. |

Keyword lists and scoring are implementation detail; the requirement is that the classifier is **pluggable** (e.g. replaceable by a VLM later) and that the output is one of these five enums.

### 4.5 estimated_extraction_cost

| Value | Definition |
|-------|------------|
| **fast_text_sufficient** | Triage indicates that fast text extraction (Strategy A) can plausibly suffice: native_digital, single_column, and no strong table/figure dominance. Downstream may still escalate on low extraction confidence. |
| **needs_layout_model** | Layout or structure matters: multi_column, table_heavy, figure_heavy, or mixed origin. Strategy B (layout-aware) should be used (or A with immediate escalation to B). |
| **needs_vision_model** | Scanned or otherwise requires vision: origin_type=scanned_image, or mixed with low confidence in text layer. Strategy C (VLM) is expected. |

**Mapping from triage to cost (required logic):**

- `origin_type = scanned_image` → `estimated_extraction_cost = needs_vision_model`.
- `origin_type = mixed` (with no override) → at least `needs_layout_model`; may be `needs_vision_model` if confidence in text is low.
- `layout_complexity` in `table_heavy`, `multi_column`, `figure_heavy`, `mixed` → `estimated_extraction_cost` at least `needs_layout_model`.
- Only when `origin_type = native_digital` and `layout_complexity = single_column` (and optionally other guards) → `fast_text_sufficient`.

---

## 5. Detection Heuristics & Signals

Requirements-level description of **what** is measured, not **how** (e.g. no API names). Exact thresholds live in config (Open Questions).

### 5.1 Origin type (digital vs. scanned vs. mixed)

- **Character density (per page or whole document):** Ratio of (character count) to (page area in consistent units, e.g. points²). Native digital pages typically have higher character density; scanned pages with no text layer have zero or near-zero.
- **Whitespace ratio:** Fraction of page area that is “empty” (no characters, no images) or low-density. Used as a secondary signal; very high may indicate image-only pages.
- **Image area ratio:** Fraction of page area occupied by embedded images or vector graphics that are not text. High image area with low character count suggests scan or figure-heavy page.
- **Font metadata presence:** Whether the PDF reports font information for text. Absence or very sparse font data can indicate scanned or OCR’d content.
- **Page-level vs. document-level:** Specification requires that “mixed” can be detected when some pages look digital and others scanned. So signals may be computed per page and then aggregated (e.g. fraction of pages with character count above a threshold).

**Requirement:** All thresholds (e.g. minimum character count per page, maximum image area ratio for “digital”) must be configurable. No hardcoded magic numbers in code.

### 5.2 Layout complexity

- **Column count / reading order:** Heuristic for number of columns (e.g. from character bbox clustering or line positions). Two or more columns → multi_column.
- **Table presence:** Either (a) explicit table detection (e.g. from a layout model or bbox grouping), or (b) proxy: regions with high density of short, aligned lines. Output: table area ratio and/or table region count per page to be compared to config thresholds for table_heavy.
- **Figure/image area:** Same image area ratio as above; compare to threshold for figure_heavy.
- **Dominance rule:** If both table and figure ratios are high, or neither clearly dominates, classification is **mixed**.

### 5.3 Language

- **Requirement:** A language detection mechanism (library or model) that returns a language code and a confidence score. No specific algorithm mandated; output must conform to DocumentProfile (ISO 639-1 + confidence in [0, 1]). If detection is not implemented, output `language=unknown`, `language_confidence=0.0`.

### 5.4 Domain hint

- **Keyword-based strategy (minimum):** A set of keywords (or phrases) per domain (financial, legal, technical, medical). Sample from document text (e.g. first N pages or full text if available). Score by presence and optionally frequency; assign domain with highest score if above a confidence threshold, else `general`. Keyword sets and thresholds must be configurable (config-over-code).
- **Pluggable:** The classifier must be replaceable (e.g. by a VLM or another service) without changing the DocumentProfile schema.

### 5.5 Triage confidence score

- **Requirement:** A single score in [0, 1] that reflects how unambiguous the classification was. For example: low when signals conflict (e.g. high character density but high image area), when values are near threshold boundaries, or when domain_hint is `general` due to no keyword match. Implementation may combine per-dimension confidences (e.g. min, product, or weighted average). Exact formula is implementation-defined; the score must be stored and used for logging and optional downstream escalation.

---

## 6. Failure Modes & Fallbacks

| Failure mode | Description | Required behavior |
|--------------|-------------|-------------------|
| **Ambiguous classification** | Signals are borderline (e.g. character density just above and image ratio just below threshold). | Emit a single, deterministic classification (no “unknown” for origin_type or layout_complexity). Set `triage_confidence_score` low. Optionally set `notes` to indicate ambiguity. Downstream may use low confidence to trigger more conservative strategy (e.g. prefer layout or vision). |
| **Conflicting signals** | e.g. Font metadata suggests digital but character count is zero (corrupted or unusual PDF). | Resolve by a defined rule order (e.g. “if character count is zero on all pages → scanned_image”) and still emit a valid DocumentProfile. Record conflict in `notes` and lower `triage_confidence_score`. |
| **Unreadable or corrupted file** | PDF cannot be opened or pages cannot be read. | Triage stage must not silently swallow the error. Emit an error (or a sentinel profile with a dedicated “error” or “unknown” state if the schema is extended) and log. Do not produce a normal DocumentProfile for the document. |
| **Empty or zero-page document** | File has no pages. | Treat as invalid input; do not emit a valid DocumentProfile; error and log. |
| **Form_fillable only** | Document is only a form with no body text. | Classify as form_fillable; layout_complexity and origin_type may be set from available signals (e.g. if no text, origin_type may be scanned_image or mixed). estimated_extraction_cost should reflect need for layout or vision if structure matters. |

**Principle:** Triage must always output a **valid** DocumentProfile for any document it accepts, with no required field left null (except optional `notes`). When in doubt, prefer the **safer, more expensive** classification (e.g. mixed over native_digital, needs_layout_model over fast_text_sufficient) so that the Extraction Layer can escalate rather than silently under-extract.

---

## 7. Non-Functional Requirements

- **Accuracy:** Triage should correctly classify the four reference document classes (A–D) as specified in §2. Target: high agreement with expected origin_type, layout_complexity, and estimated_extraction_cost for the reference corpus; exact targets (e.g. 95% on origin_type) to be set in validation and documented in Open Questions.
- **Performance:** Triage should complete in seconds per document, not minutes. Target: e.g. &lt; 30 s per document for typical PDFs (e.g. &lt; 100 pages) on reference hardware; exact target is Open Question. No VLM call is required for the default heuristic implementation.
- **Logging:** Every triage run must be logged with at least: document_id, timestamp, outcome (success / error), and the emitted DocumentProfile (or error reason). Logs must be machine-readable (e.g. JSON lines) for audit and debugging. Triage confidence score and notes must be included when present.
- **Configurability:** All thresholds (character density, image area ratio, table/figure ratios, keyword sets, confidence cutoffs) must be loaded from configuration. No hardcoded thresholds in code (constitution: config-over-code).

---

## 8. Open Questions

- **Default threshold values:** Minimum character count per page for “digital”; maximum image area ratio for “digital”; table area ratio and table count for “table_heavy”; figure area ratio for “figure_heavy”; fraction of pages for “mixed” origin. These should be set during Phase 0 exploration and documented in extraction_rules.yaml (or equivalent); spec does not fix numbers.
- **Language detection:** Whether to run language detection in triage or in a later stage; and which library/model to use. If deferred, DocumentProfile can carry `language=unknown`, `language_confidence=0.0` until implemented.
- **Form_fillable handling:** Whether form_fillable alone changes extraction strategy or only adds a hint for downstream. Current spec leaves strategy impact to Extraction Router design.
- **Schema versioning:** How DocumentProfile will be versioned (e.g. schema_version field) when new dimensions or values are added, so downstream and persisted profiles remain compatible.
- **Validation dataset:** Which labeled documents (beyond the four classes) will be used to measure triage accuracy and tune thresholds before release.

---

**Version:** 1.0  
**Spec status:** Ready for implementation; Open Questions to be closed before or during Phase 1.
