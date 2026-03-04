# Document Intelligence Refinery — Technical Report

**Version:** 1.0  
**Date:** March 5, 2025

---

## 1. Domain Notes (Phase 0 Deliverable)

Document Intelligence Refinery: extraction strategy decision tree, failure modes, pipeline diagrams, and analysis instructions.

### 1.1 Extraction Strategy Decision Tree

The Extraction Router selects strategy from DocumentProfile and escalates on low confidence:

```
                    ┌─────────────────────────────────────────────────────┐
                    │                  DocumentProfile                     │
                    │  origin_type, layout_complexity,                     │
                    │  estimated_extraction_cost                           │
                    └─────────────────────────────────────────────────────┘
                                        │
                                        ▼
        ┌───────────────────────────────────────────────────────────────────┐
        │  origin_type = scanned_image  OR  needs_vision_model?              │
        └───────────────────────────────────────────────────────────────────┘
                    │ YES                                    │ NO
                    ▼                                        ▼
        ┌───────────────────────┐              ┌─────────────────────────────────────┐
        │  Strategy C (Vision)  │              │  native_digital AND single_column?   │
        │  Start here only      │              └─────────────────────────────────────┘
        └───────────────────────┘                    │ YES              │ NO
                                                     ▼                  ▼
                                        ┌───────────────────┐  ┌───────────────────────┐
                                        │ Strategy A first  │  │ Strategy B (Layout)   │
                                        │ (FastText)        │  │ Start here directly   │
                                        └───────────────────┘  └───────────────────────┘
                                                     │
                                                     ▼
                                        ┌───────────────────┐
                                        │ confidence ≥ threshold? │
                                        └───────────────────┘
                                         │ YES        │ NO
                                         ▼            ▼
                                    [EMIT A]    [ESCALATE to B]
                                                     │
                                                     ▼
                                        ┌───────────────────┐
                                        │ Strategy B used   │
                                        │ confidence ≥ threshold? │
                                        └───────────────────┘
                                         │ YES        │ NO
                                         ▼            ▼
                                    [EMIT B]    [ESCALATE to C]
                                                     │
                                                     ▼
                                        ┌───────────────────────┐
                                        │ Strategy C (Vision)   │
                                        │ succeed? → EMIT C     │
                                        │ fail? → escalation_failed │
                                        └───────────────────────┘
```

**Summary rules (Spec 03 §7.1):**

| Condition | Action |
|-----------|--------|
| `scanned_image` or `needs_vision_model` | Strategy C only |
| `native_digital` + `single_column` | Try A → if low confidence, escalate to B |
| `multi_column`, `table_heavy`, `figure_heavy`, `mixed` | Strategy B directly |
| B used and low confidence | Escalate to C |
| C fails (budget, API error) | `escalation_failed`; no ExtractedDocument |

### 1.2 Failure Modes Observed

| Failure mode | Description | Required behavior |
|--------------|-------------|-------------------|
| **Strategy A confidence low** | Fast text unsuitable (low char density, high image ratio). | Escalate to B; do not emit A output. Log. |
| **Strategy B confidence low** | Layout extraction weak. | Escalate to C; do not emit B output. Log. |
| **Strategy C budget cap exceeded** | Document would exceed cost cap. | Halt C; log `budget_exceeded`; emit error or partial result with flag. |
| **Strategy C API failure** | VLM unavailable, timeout, rate limit. | Retry per policy; if exhausted, fail with clear error. |
| **All strategies exhausted** | A → B → C all failed. | Emit failure (no ExtractedDocument); log full escalation path. |
| **Corrupt or unreadable document** | PDF cannot be parsed. | Fail early; log; no ExtractedDocument. |
| **Partial success** | Some pages extracted, others failed. | Flag `partial=true`, `pages_missing=[...]`; ledger records partial status. |
| **Docling / MinerU not installed** | Layout backend unavailable. | Return `notes="backend docling not installed"`. |
| **Vision API not configured** | No API key or provider library missing. | Return `notes="vision_api_not_configured"`. |
| **OCR stall on scanned PDFs** | Docling/RapidOCR very slow on CPU. | Mitigate with `--max-pages`, GPU if available. |

### 1.3 Character Density & Docling Comparison

| Document type | Character density (pdfplumber) | Docling behavior |
|---------------|-------------------------------|------------------|
| Native digital, text-heavy | High density, low whitespace | Good text extraction; tables as HTML |
| Scanned image | Low density, high whitespace | OCR via RapidOCR; slower on CPU |
| Mixed (text + images) | Medium density | Layout-aware; preserves structure |
| Multi-column | Bbox spread varies | Reading-order preserved in Markdown/JSON |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                     DOCUMENT INTELLIGENCE REFINERY — 5-STAGE PIPELINE                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐     ┌──────────────┐     ┌─────────────────────┐     ┌───────────────┐     ┌─────────────────┐
  │   PDF    │     │   Stage 1    │     │      Stage 2        │     │   Stage 3     │     │   Stage 4 & 5   │
  │ Document │────▶│ Triage Agent │────▶│ Structure Extraction │────▶│   Semantic    │────▶│  PageIndex +    │
  │          │     │              │     │      (Router)       │     │   Chunking    │     │  Query Agent    │
  └──────────┘     └──────┬───────┘     └──────────┬──────────┘     └───────┬───────┘     └─────────────────┘
                          │                        │                        │
                          │ DocumentProfile        │ ExtractedDocument      │ LDUs
                          │ • origin_type          │ • text_blocks          │ • content_hash
                          │ • layout_complexity    │ • tables, figures      │ • page_refs, bbox
                          │ • estimated_cost       │ • reading_order        │
                          │                        │                        │
                          │                        │ ┌──────────────────────────────────────┐
                          │                        │ │         EXTRACTION STRATEGIES        │
                          │                        │ │  ┌─────────┐ ┌─────────┐ ┌─────────┐ │
                          │                        │ │  │   A     │ │   B     │ │   C     │ │
                          │                        │ │  │FastText │ │ Layout  │ │ Vision  │ │
                          │                        │ │  │(pdfplumb)│ │(Docling)│ │ (VLM)   │ │
                          │                        │ │  │  $0     │ │   $0    │ │  $$$    │ │
                          │                        │ │  └────┬────┘ └────┬────┘ └────┬────┘ │
                          │                        │ │       └───────────┼───────────┘      │
                          │                        │ │                   │ Escalation       │
                          │                        │ └───────────────────┼──────────────────┘
                          │                        │                     │
                          │                        │              ExtractionLedger
                          │                        │              (strategy, cost, tokens)
                          ▼                        ▼                        ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                              ARTIFACTS & STORAGE                                                       │
  │  .refinery/profiles/*.json  │  extraction_ledger.jsonl  │  vector store (LDUs)  │  pageindex/*.json   │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Technology | Role |
|-----------|------------|------|
| **Triage** | pdfplumber, pypdf | Classify origin, layout, domain; emit DocumentProfile |
| **Strategy A** | pdfplumber / pymupdf | Fast text-stream extraction; single-column native PDFs |
| **Strategy B** | Docling | Layout-aware extraction; tables, figures, multi-column |
| **Strategy C** | OpenAI GPT-4o / Gemini | Vision-based extraction; scanned images, fallback |
| **Chunking** | Structure-aware | LDUs with page_refs, bbox, content_hash |
| **PageIndex** | Hierarchical tree | Section navigation, page ranges, summaries |
| **Query Agent** | LangGraph | PageIndex-first retrieval, provenance chain |

---

## 3. Full 5-Stage Pipeline with Strategy Routing Logic

### 3.1 Stage Summary

| Stage | Name | Purpose | Key Outputs |
|-------|------|---------|-------------|
| 1 | **Triage Agent** | Classify document for strategy selection | DocumentProfile (origin_type, layout_complexity, domain_hint, estimated_extraction_cost) |
| 2 | **Structure Extraction** | Multi-strategy extraction with confidence-gated escalation | ExtractedDocument, ExtractionLedgerEntry |
| 3 | **Semantic Chunking** | Convert extraction to RAG-ready units | List of LDUs (content_hash, page_refs, bbox) |
| 4 | **PageIndex Builder** | Hierarchical document navigation | PageIndex tree (sections, page ranges, summaries) |
| 5 | **Query Interface Agent** | Answer questions with provenance | Answers + ProvenanceChain (document, page, bbox) |

### 3.2 Strategy Routing Logic (Decision Tree)

The Extraction Router (`src/agents/extractor.py`) uses `_initial_strategy_chain(profile)`:

```python
def _initial_strategy_chain(profile: DocumentProfile) -> list[str]:
    """
    - scanned_image or needs_vision_model -> [C] only
    - native_digital + single_column -> [A, B, C] (try A first, escalate)
    - else (multi_column, table_heavy, etc.) -> [B, C]
    """
    origin = profile.origin_type
    layout = profile.layout_complexity
    cost = profile.estimated_extraction_cost

    if origin == SCANNED_IMAGE or cost == NEEDS_VISION_MODEL:
        return ["vision"]
    if origin == NATIVE_DIGITAL and layout == SINGLE_COLUMN:
        return ["fast_text", "layout", "vision"]
    return ["layout", "vision"]
```

### 3.3 Escalation Flow

1. **Run strategies in chain order** until one succeeds and meets confidence threshold.
2. **Confidence thresholds** (from `extraction_rules.yaml`):
   - `fast_text_confidence_threshold`: 0.5
   - `layout_confidence_threshold`: 0.5
   - Vision: no threshold (terminal strategy).
3. **Budget guard** (before Strategy C): `check_budget(document_id, estimated_tokens)`; if false → `budget_exceeded`, no ExtractedDocument.
4. **On low confidence**: Do not emit; escalate to next strategy. Append `confidence_below_threshold` to notes.
5. **On success**: Emit ExtractedDocument, write ledger entry, optionally call `record_usage` for Strategy C.
6. **On full failure**: `strategy_used="escalation_failed"`; no ExtractedDocument; ledger records full escalation path.

### 3.4 Data Flow

```
PDF ──▶ Triage ──▶ DocumentProfile
                        │
                        ▼
PDF + Profile ──▶ ExtractionRouter
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   [Strategy A]   [Strategy B]   [Strategy C]
   (if in chain)  (if in chain)  (if in chain)
        │               │               │
        └───────────────┼───────────────┘
                        │
                        ▼
              ExtractedDocument (or None)
                        │
                        ▼
              Semantic Chunking ──▶ LDUs
                        │
                        ▼
              PageIndex Builder ──▶ PageIndex
                        │
                        ▼
              Query Agent ──▶ Answers + Provenance
```

---

## 4. Cost Analysis

### 4.1 Cost Per Document by Strategy Tier

| Strategy | Tier | Backend | API Cost | Approx. Cost per Document (10 pages) |
|----------|------|---------|----------|--------------------------------------|
| **A** | FastText | pdfplumber / pymupdf | None | **$0** |
| **B** | Layout | Docling (local) | None | **$0** |
| **C** | Vision | OpenAI / Gemini | Per page image + tokens | **$0.03 – $0.15** (typical) |

### 4.2 Strategy C — Vision Cost Breakdown

Strategy C is the only strategy that incurs API cost. Costs depend on:

- **Provider**: OpenAI (GPT-4o, GPT-4o-mini) or Google (Gemini Flash)
- **Page count**: One API call per document; all page images sent in a single request
- **Image resolution**: Default 150 DPI; `detail="low"` for OpenAI reduces token count
- **Output size**: Up to 4096 tokens per response

#### Estimated Pricing (2025)

| Provider | Model | Image Input | Text Input | Text Output | 10-Page Doc (Est.) |
|----------|-------|-------------|------------|-------------|--------------------|
| **OpenAI** | gpt-4o-mini (default) | ~$0.00286/img* | $0.15/1M tok | $0.60/1M tok | **~$0.03 – $0.06** |
| **OpenAI** | gpt-4o | ~$0.00286/img* | $5/1M tok | $15/1M tok | **~$0.05 – $0.10** |
| **Google** | Gemini Flash | ~$0.50/1M img tok | ~$0.075/1M tok | ~$3/1M tok | **~$0.01 – $0.03** |

*OpenAI charges per image (not per token) for vision; image count dominates cost.  
*Typical 10-page doc: ~10 images + ~2–5K prompt tokens + ~2–4K output tokens.

#### Cost Scaling by Page Count (Strategy C, OpenAI gpt-4o-mini)

| Pages | Est. Cost |
|-------|-----------|
| 5 | ~$0.02 |
| 10 | ~$0.04 |
| 25 | ~$0.08 |
| 50 | ~$0.15 |
| 100 | ~$0.30 |

*Assumes default 150 DPI, `detail="low"`; costs scale roughly linearly with page count.

### 4.3 Cost Optimization Strategies

1. **Strategy selection**: Triage correctly routes native digital single-column docs to Strategy A ($0) and complex layouts to B ($0), minimizing Strategy C use.
2. **Confidence gates**: Low-confidence A/B results escalate to C only when necessary.
3. **Budget cap**: `check_budget` prevents runaway costs per document.
4. **Model choice**: `gpt-4o-mini` (default) is cheaper than `gpt-4o`; Gemini Flash is often cheaper for vision-heavy workloads.
5. **Page limit**: `max_pages_per_document: 50` in config caps pages processed by Vision.
6. **Escalation ledger**: Full chain is logged so cost attribution and tuning are auditable.

### 4.4 Summary Table — Cost per Document by Strategy

| Strategy | Condition | Cost per Doc |
|----------|-----------|--------------|
| **A** | native_digital + single_column, confidence ≥ 0.5 | **$0** |
| **B** | multi_column/table_heavy/figure_heavy, or A escalated, confidence ≥ 0.5 | **$0** |
| **C** | scanned_image, needs_vision_model, or B escalated | **~$0.03 – $0.15** (10 pages, OpenAI) |
