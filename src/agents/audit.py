# Audit mode: verify claim → ProvenanceChain (verified or unverifiable). Spec 06 §7–8; plan §5.

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.models import ProvenanceChain, ProvenanceItem

# Type for retrieval: (claim, document_id?) -> list of provenance items (evidence).
SearchEvidenceCallable = Callable[[str, str | None], list[ProvenanceItem]]


UNVERIFIABLE_MESSAGE = (
    "The claim could not be verified. No supporting source was found in the corpus."
)
VERIFIED_PREFIX = "The claim is supported by the following source(s)."


@dataclass
class AuditResult:
    """Result of audit mode: response text, provenance chain, and status."""

    response_text: str
    chain: ProvenanceChain
    status: str  # "verified" | "unverifiable"

    @property
    def verified(self) -> bool:
        return self.status == "verified"


def audit_claim(
    claim: str,
    search_evidence: SearchEvidenceCallable,
    *,
    document_id: str | None = None,
    answer_id: str = "audit",
) -> AuditResult:
    """
    Audit mode: take a claim, search evidence via the provided retrieval, return
    ProvenanceChain with verified=True if evidence found, else verified=False and
    explicitly label the claim as unverifiable. No hallucinated verification.
    """
    items = search_evidence(claim, document_id)

    if not items:
        chain = ProvenanceChain(answer_id=answer_id, items=[], verified=False)
        return AuditResult(
            response_text=UNVERIFIABLE_MESSAGE,
            chain=chain,
            status="unverifiable",
        )

    chain = ProvenanceChain(answer_id=answer_id, items=items, verified=True)
    response = VERIFIED_PREFIX
    return AuditResult(
        response_text=response,
        chain=chain,
        status="verified",
    )
