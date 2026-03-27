# Triage Agent — classify document and return DocumentProfile.
# Spec: specs/02-triage-agent-and-document-profile.md, specs/07-models-schemas-spec.md §3.
# Plan: plans/phase-1-triage.plan.md

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Callable

from src.models import (
    DocumentProfile,
    DomainHint,
    EstimatedExtractionCost,
    LayoutComplexity,
    OriginType,
)

logger = logging.getLogger(__name__)

# Default config path (relative to project root or cwd).
DEFAULT_EXTRACTION_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "rubric" / "extraction_rules.yaml"


# -----------------------------------------------------------------------------
# Config loading (thresholds from rubric/extraction_rules.yaml)
# -----------------------------------------------------------------------------


def load_origin_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load origin_type thresholds from extraction_rules.yaml. No hardcoded thresholds."""
    path = config_path or DEFAULT_EXTRACTION_RULES_PATH
    if not path.exists():
        logger.warning("Config not found at %s; using built-in defaults", path)
        return {
            "min_chars_per_page_digital": 50,
            "max_image_area_ratio_digital": 0.5,
            "fraction_pages_digital_min": 0.1,
            "fraction_pages_digital_max": 0.9,
        }
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("origin_type") or {}


def load_layout_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load layout_complexity thresholds from extraction_rules.yaml. No hardcoded thresholds."""
    path = config_path or DEFAULT_EXTRACTION_RULES_PATH
    if not path.exists():
        logger.warning("Config not found at %s; using built-in defaults", path)
        return {
            "table_area_ratio_heavy": 0.25,
            "table_regions_per_page_heavy": 2,
            "figure_area_ratio_heavy": 0.4,
        }
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("layout_complexity") or {}


def load_domain_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load domain_hint keyword sets and confidence_cutoff from extraction_rules.yaml."""
    path = config_path or DEFAULT_EXTRACTION_RULES_PATH
    if not path.exists():
        logger.warning("Config not found at %s; using built-in defaults", path)
        return _default_domain_config()
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    section = data.get("domain_hint") or {}
    if not section.get("keywords"):
        section = {**section, "keywords": _default_domain_config().get("keywords", {})}
    return section


def _default_domain_config() -> dict[str, Any]:
    """Minimal default keyword sets when config is missing (spec §4.4)."""
    return {
        "confidence_cutoff": 0.3,
        "sample_max_pages": 5,
        "keywords": {
            "financial": ["revenue", "balance sheet", "fiscal", "audit", "expenditure"],
            "legal": ["whereas", "hereby", "clause", "agreement", "court"],
            "technical": ["implementation", "assessment", "methodology", "findings"],
            "medical": ["patient", "diagnosis", "treatment", "clinical"],
        },
    }


# -----------------------------------------------------------------------------
# PDF signal extraction (text density, image ratio, form_fillable)
# -----------------------------------------------------------------------------


def extract_pdf_signals(pdf_path: Path) -> dict[str, Any]:
    """
    Extract measurable signals for origin_type and layout_complexity: chars per page,
    image area ratio per page, table area ratio per page, table regions per page,
    column-count heuristic per page, page count, form_fillable.
    """
    import pdfplumber
    from pypdf import PdfReader

    signals: dict[str, Any] = {
        "page_count": 0,
        "chars_per_page": [],
        "image_area_ratio_per_page": [],
        "form_fillable": False,
        "table_area_ratio_per_page": [],
        "table_regions_per_page": [],
        "columns_per_page": [],
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            signals["page_count"] = len(pdf.pages)
            for page in pdf.pages:
                char_count = len(page.chars) if page.chars else 0
                signals["chars_per_page"].append(char_count)

                page_area = float(page.width * page.height) if page.width and page.height else 1.0
                image_area = 0.0
                for im in page.images or []:
                    w = im.get("width") or 0
                    h = im.get("height") or 0
                    image_area += float(w * h)
                ratio = image_area / page_area if page_area > 0 else 0.0
                signals["image_area_ratio_per_page"].append(min(ratio, 1.0))

                # Layout: table area ratio and table count per page
                table_area = 0.0
                tables = page.find_tables() if hasattr(page, "find_tables") else []
                for t in tables:
                    bbox = getattr(t, "bbox", None) or (0, 0, 0, 0)
                    table_area += float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
                signals["table_area_ratio_per_page"].append(
                    min(table_area / page_area, 1.0) if page_area > 0 else 0.0
                )
                signals["table_regions_per_page"].append(len(tables))

                # Column heuristic: cluster char x0 into buckets; 2+ buckets with chars → multi-column
                width = float(page.width or 1)
                if page.chars and width > 0:
                    buckets = [0] * 5
                    for c in page.chars:
                        x0 = c.get("x0") or 0
                        idx = max(0, min(4, int((x0 / width) * 5)))
                        buckets[idx] = 1
                    signals["columns_per_page"].append(sum(buckets))
                else:
                    signals["columns_per_page"].append(1)

        reader = PdfReader(str(pdf_path))
        fields = reader.get_fields()
        signals["form_fillable"] = bool(fields and len(fields) > 0)
    except Exception as e:
        logger.exception("extract_pdf_signals failed for %s: %s", pdf_path, e)
        raise

    return signals


# -----------------------------------------------------------------------------
# Origin type from signals (rule order: all zero → scanned; fraction → mixed; else digital)
# -----------------------------------------------------------------------------


def compute_origin_from_signals(signals: dict[str, Any], config: dict[str, Any]) -> tuple[OriginType, float, dict[str, Any]]:
    """
    Compute origin_type, confidence, and metadata from extracted signals.
    Rule order (spec): all pages zero chars → scanned_image; fraction digital in (min,max) → mixed; else native_digital.
    """
    min_chars = config.get("min_chars_per_page_digital", 50)
    max_image_ratio = config.get("max_image_area_ratio_digital", 0.5)
    frac_min = config.get("fraction_pages_digital_min", 0.1)
    frac_max = config.get("fraction_pages_digital_max", 0.9)

    chars_per_page = signals.get("chars_per_page") or []
    image_ratio_per_page = signals.get("image_area_ratio_per_page") or []
    form_fillable = signals.get("form_fillable", False)
    page_count = len(chars_per_page)

    if page_count == 0:
        return OriginType.SCANNED_IMAGE, 0.0, {"reason": "zero_pages", **signals}

    digital_pages = sum(1 for c in chars_per_page if c >= min_chars)
    fraction_digital = digital_pages / page_count

    mean_image_ratio = sum(image_ratio_per_page) / page_count if page_count else 0.0
    metadata = {
        "chars_per_page": chars_per_page,
        "image_area_ratio_per_page": image_ratio_per_page,
        "fraction_pages_digital": fraction_digital,
        "form_fillable": form_fillable,
        "min_chars_per_page_digital": min_chars,
    }

    # Rule order: all pages below min chars → scanned_image
    if digital_pages == 0:
        logger.debug("origin_type=scanned_image (zero pages with >= %s chars)", min_chars)
        return OriginType.SCANNED_IMAGE, 0.9, {**metadata, "reason": "all_pages_below_min_chars"}

    # Some but not all pages digital → mixed
    if frac_min < fraction_digital < frac_max:
        confidence = 0.85
        if mean_image_ratio > max_image_ratio:
            confidence = 0.6
        logger.debug("origin_type=mixed (fraction_digital=%.2f)", fraction_digital)
        return OriginType.MIXED, confidence, {**metadata, "reason": "fraction_pages_digital_in_range"}

    # All pages digital
    if fraction_digital >= frac_max:
        if mean_image_ratio <= max_image_ratio:
            confidence = 0.95
            return OriginType.NATIVE_DIGITAL, confidence, {**metadata, "reason": "all_digital_low_image"}
        # High image ratio but still all digital (e.g. illustrated doc)
        confidence = 0.75
        return OriginType.NATIVE_DIGITAL, confidence, {**metadata, "reason": "all_digital_high_image"}

    # fraction_digital <= frac_min but digital_pages > 0 → mixed with low confidence
    return OriginType.MIXED, 0.6, {**metadata, "reason": "few_pages_digital"}


# -----------------------------------------------------------------------------
# detect_origin_type: (origin_type, confidence, metadata_signals)
# -----------------------------------------------------------------------------


def detect_origin_type(
    pdf_path: Path,
    config_path: Path | None = None,
    *,
    signals: dict[str, Any] | None = None,
) -> tuple[OriginType, float, dict[str, Any]]:
    """
    Classify origin: native_digital | scanned_image | mixed | form_fillable.
    Returns (origin_type, confidence, metadata_signals).
    If signals is provided (e.g. from tests), skip PDF extraction and use them.
    """
    config = load_origin_config(config_path)
    if signals is not None:
        return compute_origin_from_signals(signals, config)

    logger.debug("detect_origin_type(%s) — extracting signals", pdf_path)
    extracted = extract_pdf_signals(pdf_path)
    return compute_origin_from_signals(extracted, config)


# -----------------------------------------------------------------------------
# Layout complexity from signals (table/figure ratio, column heuristic; dominance → mixed)
# -----------------------------------------------------------------------------


def compute_layout_from_signals(
    signals: dict[str, Any], config: dict[str, Any]
) -> tuple[LayoutComplexity, float, dict[str, Any]]:
    """
    Compute layout_complexity, confidence, and metadata from extracted signals.
    Dominance rule (spec): both table and figure high → mixed; else table_heavy | figure_heavy | multi_column | single_column.
    """
    table_ratio_heavy = config.get("table_area_ratio_heavy", 0.25)
    table_regions_heavy = config.get("table_regions_per_page_heavy", 2)
    figure_ratio_heavy = config.get("figure_area_ratio_heavy", 0.4)

    table_ratio_per_page = signals.get("table_area_ratio_per_page") or []
    table_regions_per_page = signals.get("table_regions_per_page") or []
    image_ratio_per_page = signals.get("image_area_ratio_per_page") or []
    columns_per_page = signals.get("columns_per_page") or []

    page_count = len(table_ratio_per_page) or 1
    mean_table_ratio = sum(table_ratio_per_page) / page_count if page_count else 0.0
    mean_figure_ratio = sum(image_ratio_per_page) / page_count if page_count else 0.0
    mean_table_regions = sum(table_regions_per_page) / page_count if page_count else 0.0
    max_columns = max(columns_per_page) if columns_per_page else 1

    metadata = {
        "table_area_ratio_per_page": table_ratio_per_page,
        "table_regions_per_page": table_regions_per_page,
        "image_area_ratio_per_page": image_ratio_per_page,
        "columns_per_page": columns_per_page,
        "mean_table_area_ratio": mean_table_ratio,
        "mean_figure_area_ratio": mean_figure_ratio,
        "mean_table_regions_per_page": mean_table_regions,
        "max_columns": max_columns,
    }

    table_heavy = mean_table_ratio >= table_ratio_heavy or mean_table_regions >= table_regions_heavy
    figure_heavy = mean_figure_ratio >= figure_ratio_heavy
    multi_column = max_columns >= 2

    if table_heavy and figure_heavy:
        return LayoutComplexity.MIXED, 0.85, {**metadata, "reason": "both_table_and_figure_heavy"}
    if table_heavy:
        return LayoutComplexity.TABLE_HEAVY, 0.9, {**metadata, "reason": "table_area_or_count_above_threshold"}
    if figure_heavy:
        return LayoutComplexity.FIGURE_HEAVY, 0.9, {**metadata, "reason": "figure_area_above_threshold"}
    if multi_column:
        return LayoutComplexity.MULTI_COLUMN, 0.85, {**metadata, "reason": "multi_column_heuristic"}
    return LayoutComplexity.SINGLE_COLUMN, 0.95, {**metadata, "reason": "single_column_low_table_figure"}


def detect_layout_complexity(
    pdf_path: Path,
    config_path: Path | None = None,
    *,
    signals: dict[str, Any] | None = None,
) -> tuple[LayoutComplexity, float, dict[str, Any]]:
    """
    Classify layout: single_column | multi_column | table_heavy | figure_heavy | mixed.
    Returns (layout_complexity, confidence, metadata_signals).
    If signals is provided (e.g. from tests), skip PDF extraction.
    """
    config = load_layout_config(config_path)
    if signals is not None:
        return compute_layout_from_signals(signals, config)
    logger.debug("detect_layout_complexity(%s) — extracting signals", pdf_path)
    extracted = extract_pdf_signals(pdf_path)
    return compute_layout_from_signals(extracted, config)


# -----------------------------------------------------------------------------
# Domain hint from sample text (keyword-based, pluggable) — P1-T005
# -----------------------------------------------------------------------------


def extract_sample_text(pdf_path: Path, max_pages: int = 5) -> str:
    """Extract text from first max_pages for domain keyword scoring. Cheap parsing (pdfplumber)."""
    import pdfplumber
    try:
        with pdfplumber.open(pdf_path) as pdf:
            parts = []
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                text = page.extract_text()
                if text:
                    parts.append(text)
            return " ".join(parts).lower()
    except Exception as e:
        logger.warning("extract_sample_text failed for %s: %s", pdf_path, e)
        return ""


def _keyword_matches(sample_lower: str, word_set: set[str], term_list: list[str]) -> tuple[int, list[str]]:
    """Transparent keyword scoring: count how many terms appear in text and return matched keywords."""
    matched: list[str] = []
    for t in term_list:
        if t in word_set or any(t in w for w in word_set) or (t in sample_lower):
            matched.append(t)
    return len(matched), matched


def compute_domain_from_text(
    sample_text: str, config: dict[str, Any]
) -> tuple[DomainHint, float, dict[str, Any]]:
    """
    Baseline domain_hint classifier: keyword scoring with transparent logic.
    Score = (number of keywords matched) / (len(term_list)//2); assign domain if score >= confidence_cutoff else general.
    Returns (domain_hint, confidence, metadata) with domain_scores, domain_hits, matched_keywords, domain_confidence.
    """
    confidence_cutoff = config.get("confidence_cutoff", 0.3)
    keywords_cfg = config.get("keywords") or _default_domain_config().get("keywords", {})
    words = sample_text.split() if sample_text else []
    word_set = set(w.strip(".,;:!?") for w in words if len(w) > 1)
    sample_lower = sample_text.lower()

    scores: dict[str, float] = {}
    hits: dict[str, int] = {}
    matched_by_domain: dict[str, list[str]] = {}
    for domain_key, terms in keywords_cfg.items():
        domain_key_lower = domain_key.lower()
        if domain_key_lower not in ("financial", "legal", "technical", "medical"):
            continue
        term_list = [t.lower() for t in (terms if isinstance(terms, list) else [])]
        count, matched = _keyword_matches(sample_lower, word_set, term_list)
        hits[domain_key_lower] = count
        matched_by_domain[domain_key_lower] = matched
        if term_list:
            scores[domain_key_lower] = min(1.0, count / max(1, len(term_list) // 2))
        else:
            scores[domain_key_lower] = 0.0

    if not scores:
        return DomainHint.GENERAL, 0.0, {
            "reason": "no_keywords_configured",
            "domain_scores": {},
            "domain_hits": {},
            "matched_keywords": [],
        }

    best_domain = max(scores, key=scores.get)
    best_score = scores[best_domain]
    top_matched = matched_by_domain.get(best_domain, [])

    if best_score >= confidence_cutoff and hits.get(best_domain, 0) > 0:
        domain_enum = {
            "financial": DomainHint.FINANCIAL,
            "legal": DomainHint.LEGAL,
            "technical": DomainHint.TECHNICAL,
            "medical": DomainHint.MEDICAL,
        }.get(best_domain, DomainHint.GENERAL)
        confidence = min(0.95, confidence_cutoff + best_score * 0.5)
        return domain_enum, confidence, {
            "reason": "keyword_match",
            "domain_scores": scores,
            "domain_hits": hits,
            "chosen_domain": best_domain,
            "chosen_score": best_score,
            "domain_confidence": confidence,
            "matched_keywords": top_matched,
        }
    return DomainHint.GENERAL, 0.5, {
        "reason": "below_cutoff_or_no_hits",
        "domain_scores": scores,
        "domain_hits": hits,
        "domain_confidence": 0.5,
        "matched_keywords": [],
    }


def detect_domain_hint(
    pdf_path: Path,
    config_path: Path | None = None,
    *,
    text: str | None = None,
) -> tuple[DomainHint, float, dict[str, Any]]:
    """
    Classify domain: financial | legal | technical | medical | general.
    Returns (domain_hint, confidence, metadata_signals).
    If text is provided (e.g. from tests), skip PDF extraction.
    Pluggable: pass a different domain_fn to TriageAgent to swap implementation.
    """
    config = load_domain_config(config_path)
    if text is not None:
        return compute_domain_from_text(text, config)
    max_pages = config.get("sample_max_pages", 5)
    logger.debug("detect_domain_hint(%s) — sampling up to %s pages", pdf_path, max_pages)
    sample = extract_sample_text(pdf_path, max_pages=max_pages)
    return compute_domain_from_text(sample, config)


def get_page_count(pdf_path: Path) -> int:
    """Return number of pages from PDF."""
    try:
        sig = extract_pdf_signals(pdf_path)
        return sig["page_count"] or 1
    except Exception:
        logger.warning("get_page_count failed, defaulting to 1")
        return 1


def derive_estimated_extraction_cost(origin: OriginType, layout: LayoutComplexity) -> EstimatedExtractionCost:
    """Derive cost tier from origin_type and layout_complexity (spec invariants)."""
    if origin == OriginType.SCANNED_IMAGE:
        return EstimatedExtractionCost.NEEDS_VISION_MODEL
    if layout in (
        LayoutComplexity.TABLE_HEAVY,
        LayoutComplexity.MULTI_COLUMN,
        LayoutComplexity.FIGURE_HEAVY,
        LayoutComplexity.MIXED,
    ):
        return EstimatedExtractionCost.NEEDS_LAYOUT_MODEL
    if origin == OriginType.NATIVE_DIGITAL and layout == LayoutComplexity.SINGLE_COLUMN:
        return EstimatedExtractionCost.FAST_TEXT_SUFFICIENT
    return EstimatedExtractionCost.NEEDS_LAYOUT_MODEL


def derive_document_id(pdf_path: Path) -> str:
    """Stable document_id from file path (e.g. hash). Same path → same id."""
    path_str = str(pdf_path.resolve())
    return hashlib.sha256(path_str.encode()).hexdigest()[:32]


# -----------------------------------------------------------------------------
# TriageAgent — DI-friendly; origin_fn returns (OriginType, confidence, metadata)
# -----------------------------------------------------------------------------


class TriageAgent:
    """
    Classify a PDF and return a DocumentProfile.
    origin_fn and layout_fn may return (type, confidence, metadata) or legacy single value.
    """

    def __init__(
        self,
        *,
        origin_fn: Callable[..., tuple[OriginType, float, dict[str, Any]]] | Callable[[Path], OriginType] | None = None,
        layout_fn: Callable[..., tuple[LayoutComplexity, float, dict[str, Any]]] | Callable[[Path], LayoutComplexity] | None = None,
        domain_fn: Callable[..., tuple[DomainHint, float, dict[str, Any]]] | Callable[[Path], DomainHint] | None = None,
        page_count_fn: Callable[[Path], int] | None = None,
        document_id_fn: Callable[[Path], str] | None = None,
        config_path: Path | None = None,
    ):
        self._origin = origin_fn or (lambda p: detect_origin_type(p, config_path))
        self._layout = layout_fn or (lambda p: detect_layout_complexity(p, config_path))
        self._domain = domain_fn or (lambda p: detect_domain_hint(p, config_path))
        self._page_count = page_count_fn or get_page_count
        self._document_id = document_id_fn or derive_document_id

    def run(self, pdf_path: str | Path) -> DocumentProfile:
        """Run triage on a single PDF; return DocumentProfile."""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        if path.suffix.lower() != ".pdf":
            logger.warning("File is not .pdf: %s", path)

        document_id = self._document_id(path)
        page_count = self._page_count(path)
        origin_result = self._origin(path)
        layout_result = self._layout(path)
        domain_result = self._domain(path)

        # Unpack (origin_type, confidence, metadata) or plain OriginType
        if isinstance(origin_result, tuple) and len(origin_result) == 3:
            origin_type, origin_confidence, origin_metadata = origin_result
        else:
            origin_type = origin_result
            origin_confidence = 0.8
            origin_metadata = {}

        # Unpack (layout_complexity, confidence, metadata) or plain LayoutComplexity
        if isinstance(layout_result, tuple) and len(layout_result) == 3:
            layout_complexity, layout_confidence, layout_metadata = layout_result
        else:
            layout_complexity = layout_result
            layout_confidence = 0.8
            layout_metadata = {}

        # Unpack (domain_hint, confidence, metadata) or plain DomainHint
        if isinstance(domain_result, tuple) and len(domain_result) == 3:
            domain_hint, domain_confidence, domain_metadata = domain_result
        else:
            domain_hint = domain_result
            domain_confidence = 0.8
            domain_metadata = {}

        estimated_extraction_cost = derive_estimated_extraction_cost(origin_type, layout_complexity)

        # Aggregate triage confidence (min of origin, layout, domain)
        triage_confidence_score = min(origin_confidence, layout_confidence, domain_confidence)
        metadata = {**origin_metadata, **layout_metadata, **domain_metadata} or None

        logger.info(
            "triage result document_id=%s origin=%s layout=%s cost=%s confidence=%.2f",
            document_id,
            origin_type.value,
            layout_complexity.value,
            estimated_extraction_cost.value,
            triage_confidence_score,
        )

        return DocumentProfile(
            document_id=document_id,
            origin_type=origin_type,
            layout_complexity=layout_complexity,
            language="en",
            language_confidence=0.5,
            domain_hint=domain_hint,
            estimated_extraction_cost=estimated_extraction_cost,
            triage_confidence_score=triage_confidence_score,
            page_count=page_count,
            metadata=metadata,
        )


# -----------------------------------------------------------------------------
# Module-level entrypoint
# -----------------------------------------------------------------------------


def run_triage(pdf_path: str | Path, *, agent: TriageAgent | None = None) -> DocumentProfile:
    """Run triage on a PDF; returns DocumentProfile."""
    if agent is None:
        agent = TriageAgent()
    return agent.run(pdf_path)
