# ChunkValidator — enforce 5 chunking rules and provenance. Spec 04 §6; plan §3.2.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.models import LDU, LDUContentType

if TYPE_CHECKING:
    pass


@dataclass
class ValidationResult:
    """Result of validating a list of LDUs. Fail loudly with clear error messages."""

    success: bool = True
    errors: list[str] = field(default_factory=list)
    ldus: list[LDU] | None = None

    def __post_init__(self) -> None:
        if not self.success and not self.errors:
            self.errors = ["Validation failed with no error messages."]


class ChunkValidationError(Exception):
    """Raised when ChunkValidator rejects the LDU list. Contains ValidationResult."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__("; ".join(result.errors))


class ChunkValidator:
    """
    Enforces the 5 chunking rules and provenance before emitting LDUs.
    Rejects: split table header/body, figure without caption, broken lists,
    missing section metadata after section header, missing page_refs/bbox/content_hash.
    """

    def validate(self, ldus: list[LDU]) -> ValidationResult:
        """
        Run all checks. Returns ValidationResult with success=True and ldus if valid;
        otherwise success=False and errors list with clear messages.
        """
        errors: list[str] = []
        if not ldus:
            return ValidationResult(success=True, ldus=[])

        # 1. Provenance: every LDU has non-empty page_refs, bounding_boxes, content_hash
        for i, ldu in enumerate(ldus):
            if not ldu.page_refs:
                errors.append(f"LDU[{i}] id={ldu.id!r}: page_refs must be non-empty (missing provenance).")
            if not ldu.bounding_boxes:
                errors.append(f"LDU[{i}] id={ldu.id!r}: bounding_boxes must be non-empty (missing provenance).")
            if not (ldu.content_hash or "").strip():
                errors.append(f"LDU[{i}] id={ldu.id!r}: content_hash must be non-empty.")

        # 2. No table split: no header-only LDU followed by body-only table LDU
        table_types = (LDUContentType.TABLE, LDUContentType.TABLE_SECTION)
        for i in range(len(ldus) - 1):
            a, b = ldus[i], ldus[i + 1]
            if a.content_type not in table_types or b.content_type not in table_types:
                continue
            header_only = _table_has_header_only(a)
            body_only = _table_has_body_only(b)
            if header_only and body_only:
                errors.append(
                    f"Chunking rule 1 violated: table split across LDUs. "
                    f"LDU[{i}] id={a.id!r} has header only; LDU[{i+1}] id={b.id!r} has rows only. "
                    "Each table part must include the header row."
                )

        # 3. Figure + caption unity: every figure LDU must include caption (in text or raw_payload)
        for i, ldu in enumerate(ldus):
            if ldu.content_type != LDUContentType.FIGURE:
                continue
            has_caption = (ldu.text or "").strip() or (ldu.raw_payload or {}).get("caption") or (ldu.raw_payload or {}).get("caption_text")
            if not has_caption:
                errors.append(
                    f"Chunking rule 2 violated: figure LDU[{i}] id={ldu.id!r} has no caption. "
                    "Figure and caption must be in the same LDU."
                )

        # 4. List integrity: no list LDU split mid-item (raw_payload.list_complete must not be False)
        for i, ldu in enumerate(ldus):
            if ldu.content_type != LDUContentType.LIST:
                continue
            if ldu.raw_payload.get("list_complete") is False:
                errors.append(
                    f"Chunking rule 3 violated: list LDU[{i}] id={ldu.id!r} is split mid-item. "
                    "Lists must be split only at list item boundaries."
                )
            if _list_text_ends_mid_item(ldu.text):
                errors.append(
                    f"Chunking rule 3 violated: list LDU[{i}] id={ldu.id!r} text ends with incomplete item. "
                    "Lists must not be split mid-item."
                )

        # 5. Section metadata: after a section_intro, every LDU until the next section_intro must have parent_section_id
        current_section_ldu_id: str | None = None
        for i, ldu in enumerate(ldus):
            if ldu.content_type == LDUContentType.SECTION_INTRO:
                current_section_ldu_id = ldu.id
                continue
            if current_section_ldu_id is not None and (ldu.parent_section_id is None or ldu.parent_section_id == ""):
                errors.append(
                    f"Chunking rule 4 violated: LDU[{i}] id={ldu.id!r} has no parent_section_id. "
                    f"Section header (LDU {current_section_ldu_id!r}) exists; content LDUs must have parent_section_id set."
                )

        if errors:
            return ValidationResult(success=False, errors=errors, ldus=None)
        return ValidationResult(success=True, errors=[], ldus=ldus)

    def validate_or_raise(self, ldus: list[LDU]) -> list[LDU]:
        """Run validate(); on failure raise ChunkValidationError with clear messages."""
        result = self.validate(ldus)
        if not result.success:
            raise ChunkValidationError(result)
        return result.ldus or []


# Default validator instance for use by ChunkingEngine
_default_validator = ChunkValidator()


def emit_ldus(ldus: list[LDU], validator: ChunkValidator | None = None) -> list[LDU]:
    """
    Run ChunkValidator before emitting. ChunkingEngine must call this (or
    validator.validate_or_raise) before returning LDUs. Raises ChunkValidationError on failure.
    """
    v = validator or _default_validator
    return v.validate_or_raise(ldus)


def _table_has_header_only(ldu: LDU) -> bool:
    """True if LDU looks like table header only (has header/headers, no or empty rows)."""
    r = ldu.raw_payload or {}
    has_header = "header" in r or "headers" in r
    rows = r.get("rows", r.get("data", []))
    return bool(has_header and (not rows or len(rows) == 0))


def _table_has_body_only(ldu: LDU) -> bool:
    """True if LDU looks like table body only (has rows, no header or empty header)."""
    r = ldu.raw_payload or {}
    rows = r.get("rows", r.get("data", []))
    if not rows:
        return False
    header = r.get("header") or r.get("headers")
    if header is None:
        return True
    if isinstance(header, list) and len(header) == 0:
        return True
    return False


def _list_text_ends_mid_item(text: str) -> bool:
    """Heuristic: text ends with incomplete list item (e.g. trailing space, or line that looks like start of item with no content)."""
    if not (text or "").strip():
        return False
    t = text.rstrip()
    if t.endswith(" ") or t.endswith("\t"):
        return True
    lines = t.split("\n")
    if not lines:
        return False
    last = lines[-1].strip()
    if not last:
        return False
    if last and last[0].isdigit() and "." in last[:4]:
        rest = last.split(".", 1)[-1].strip()
        if not rest or len(rest) < 2:
            return True
    return False
