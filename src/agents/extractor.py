# ExtractionRouter — single entry point for extraction; decision tree, escalation, ledger. Spec 03 §7; plan §4.

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.models import (
    DocumentProfile,
    EstimatedExtractionCost,
    ExtractionLedgerEntry,
    ExtractedDocument,
    LayoutComplexity,
    OriginType,
)
from src.refinery.ledger import append_ledger_entry
from src.strategies.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "rubric" / "extraction_rules.yaml"

# Strategy names in escalation order (A -> B -> C).
STRATEGY_ORDER = ["fast_text", "layout", "vision"]


def _load_router_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load router section from extraction_rules.yaml (confidence thresholds)."""
    path = config_path or _DEFAULT_RULES_PATH
    if not path.exists():
        return {
            "fast_text_confidence_threshold": 0.5,
            "layout_confidence_threshold": 0.5,
        }
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("router") or {
        "fast_text_confidence_threshold": 0.5,
        "layout_confidence_threshold": 0.5,
    }


def _initial_strategy_chain(profile: DocumentProfile) -> list[str]:
    """
    Decision tree: which strategies to try, in order (spec 03 §7.1; plan §4.2).
    - scanned_image or needs_vision_model -> [C] only.
    - native_digital + single_column -> [A, B, C].
    - else (multi_column, table_heavy, etc.) -> [B, C].
    """
    origin = profile.origin_type
    layout = profile.layout_complexity
    cost = profile.estimated_extraction_cost

    if origin == OriginType.SCANNED_IMAGE or cost == EstimatedExtractionCost.NEEDS_VISION_MODEL:
        return ["vision"]
    if origin == OriginType.NATIVE_DIGITAL and layout == LayoutComplexity.SINGLE_COLUMN:
        return ["fast_text", "layout", "vision"]
    return ["layout", "vision"]


def _threshold_for_strategy(strategy_name: str, config: dict[str, Any]) -> float:
    if strategy_name == "fast_text":
        return config.get("fast_text_confidence_threshold", 0.5)
    if strategy_name == "layout":
        return config.get("layout_confidence_threshold", 0.5)
    return 0.0


# -----------------------------------------------------------------------------
# Budget guard hooks (minimal; no-op by default)
# -----------------------------------------------------------------------------


def _noop_check_budget(document_id: str, estimated_tokens: int) -> bool:
    """Default: allow (no cap)."""
    return True


def _noop_record_usage(
    document_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    """Default: no-op."""
    pass


# -----------------------------------------------------------------------------
# ExtractionRouter
# -----------------------------------------------------------------------------


class ExtractionRouter:
    """
    Single entry point for extraction. Selects initial strategy from profile,
    runs extractors in order, escalates on low confidence, never passes
    low-confidence output downstream. Writes one ExtractionLedgerEntry per run.
    """

    def __init__(
        self,
        fast_text_extractor: BaseExtractor,
        layout_extractor: BaseExtractor,
        vision_extractor: BaseExtractor,
        *,
        ledger_path: Path | str | None = None,
        config_path: Path | None = None,
        check_budget: Callable[[str, int], bool] | None = None,
        record_usage: Callable[[str, int, int, float], None] | None = None,
    ) -> None:
        self._fast_text = fast_text_extractor
        self._layout = layout_extractor
        self._vision = vision_extractor
        self._ledger_path = ledger_path
        self._config_path = config_path
        self._check_budget = check_budget or _noop_check_budget
        self._record_usage = record_usage or _noop_record_usage
        self._extractors: dict[str, BaseExtractor] = {
            "fast_text": fast_text_extractor,
            "layout": layout_extractor,
            "vision": vision_extractor,
        }

    def extract(
        self,
        doc_path: Path | str,
        profile: DocumentProfile,
    ) -> tuple[ExtractedDocument | None, ExtractionResult]:
        """
        Run extraction with escalation. Returns (document or None, final ExtractionResult).
        Always writes one ExtractionLedgerEntry to the ledger after the run.
        """
        doc_path = Path(doc_path)
        config = _load_router_config(self._config_path)
        chain = _initial_strategy_chain(profile)
        start_time = datetime.now(timezone.utc)
        start_ts = time.perf_counter()
        escalation_chain: list[str] = []
        last_result: ExtractionResult | None = None
        accepted_document: ExtractedDocument | None = None
        notes_parts: list[str] = []

        for strategy_name in chain:
            # Before Strategy C: budget guard (spec 03 §8; plan §4.4)
            if strategy_name == "vision":
                if not self._check_budget(profile.document_id, 0):
                    notes_parts.append("budget_exceeded")
                    escalation_chain.append("vision")
                    last_result = ExtractionResult(
                        extracted_document=None,
                        confidence_score=last_result.confidence_score if last_result else 0.0,
                        cost_estimate_usd=0.0,
                        strategy_name="vision",
                        notes="budget_exceeded",
                    )
                    break

            extractor = self._extractors[strategy_name]
            result = extractor.extract(doc_path, profile)
            last_result = result
            escalation_chain.append(strategy_name)

            if result.success:
                threshold = _threshold_for_strategy(strategy_name, config)
                if result.confidence_score >= threshold:
                    accepted_document = result.extracted_document
                    if result.notes:
                        notes_parts.append(result.notes)
                    break
                # Low confidence: do not emit; escalate
                notes_parts.append("confidence_below_threshold")
                continue
            # Escalation or error from this strategy
            if result.notes:
                notes_parts.append(result.notes)
            continue

        end_ts = time.perf_counter()
        end_time = datetime.now(timezone.utc)
        processing_time_ms = int((end_ts - start_ts) * 1000)

        if accepted_document is not None:
            strategy_used = escalation_chain[-1]
            confidence_score = last_result.confidence_score if last_result else 0.0
            cost_estimate_usd = last_result.cost_estimate_usd if last_result else 0.0
            token_prompt = last_result.token_usage_prompt if last_result else None
            token_completion = last_result.token_usage_completion if last_result else None
        else:
            strategy_used = "escalation_failed"
            confidence_score = last_result.confidence_score if last_result else 0.0
            cost_estimate_usd = last_result.cost_estimate_usd if last_result else 0.0
            token_prompt = last_result.token_usage_prompt if last_result else None
            token_completion = last_result.token_usage_completion if last_result else None

        notes_str = "; ".join(notes_parts) if notes_parts else None

        origin_str = getattr(profile.origin_type, "value", str(profile.origin_type))
        layout_str = getattr(profile.layout_complexity, "value", str(profile.layout_complexity))

        entry = ExtractionLedgerEntry(
            document_id=profile.document_id,
            strategy_used=strategy_used,
            origin_type=origin_str,
            layout_complexity=layout_str,
            start_time=start_time,
            end_time=end_time,
            processing_time_ms=processing_time_ms,
            confidence_score=confidence_score,
            cost_estimate_usd=cost_estimate_usd,
            token_usage_prompt=token_prompt,
            token_usage_completion=token_completion,
            escalation_chain=escalation_chain,
            notes=notes_str,
        )
        append_ledger_entry(entry, ledger_path=self._ledger_path)

        if accepted_document is not None and strategy_used == "vision" and (token_prompt or token_completion):
            self._record_usage(
                profile.document_id,
                token_prompt or 0,
                token_completion or 0,
                cost_estimate_usd,
            )

        final_result = last_result if last_result else ExtractionResult(
            extracted_document=None,
            confidence_score=0.0,
            cost_estimate_usd=0.0,
            strategy_name=escalation_chain[-1] if escalation_chain else "fast_text",
            notes=notes_str,
        )
        return accepted_document, final_result
