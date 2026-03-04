# ExtractionLedgerEntry — one row per extraction run. Spec 07 §9.1.

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ExtractionLedgerEntry(BaseModel):
    """Single immutable ledger entry for an extraction run. Serialized as one JSONL line."""

    document_id: str = Field(..., min_length=1)
    strategy_used: str = Field(
        ...,
        pattern="^(fast_text|layout|vision|escalation_failed)$",
        description="Final strategy that produced output, or escalation_failed if none.",
    )
    origin_type: str = Field(..., min_length=1)
    layout_complexity: str = Field(..., min_length=1)
    start_time: datetime = Field(..., description="Run start (ISO 8601 in JSON).")
    end_time: datetime = Field(..., description="Run end (ISO 8601 in JSON).")
    processing_time_ms: int = Field(..., ge=0)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    cost_estimate_usd: float = Field(..., ge=0.0)
    token_usage_prompt: int | None = None
    token_usage_completion: int | None = None
    escalation_chain: list[str] = Field(
        ...,
        min_length=0,
        description="Ordered strategies attempted; when succeeded, last must equal strategy_used.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def end_time_after_start_time(self) -> "ExtractionLedgerEntry":
        if self.end_time < self.start_time:
            raise ValueError("end_time must be >= start_time")
        return self

    @model_validator(mode="after")
    def strategy_used_matches_escalation_chain_when_succeeded(self) -> "ExtractionLedgerEntry":
        if self.strategy_used == "escalation_failed":
            return self
        if not self.escalation_chain:
            raise ValueError("escalation_chain must be non-empty when strategy_used is not escalation_failed")
        if self.escalation_chain[-1] != self.strategy_used:
            raise ValueError(
                f"strategy_used ({self.strategy_used!r}) must equal last element of escalation_chain ({self.escalation_chain[-1]!r})"
            )
        return self

    model_config = {"frozen": True}


__all__ = ["ExtractionLedgerEntry"]
