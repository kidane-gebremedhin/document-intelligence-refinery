# ChunkValidator — enforce 5 chunking rules and provenance. Spec 04 §6; spec 07 §5.4.
# No partial enforcement: validator fails loudly with clear error codes.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.models import LDU, LDUContentType

if TYPE_CHECKING:
    pass


# Error codes per spec 04 §5.6 and §6.1; spec 07 §5.4
TABLE_HEADER_CELLS_SPLIT = "TABLE_HEADER_CELLS_SPLIT"
FIGURE_CAPTION_NOT_UNIFIED = "FIGURE_CAPTION_NOT_UNIFIED"
LIST_MID_ITEM_SPLIT = "LIST_MID_ITEM_SPLIT"
PARENT_SECTION_MISSING = "PARENT_SECTION_MISSING"
PAGE_REFS_EMPTY = "PAGE_REFS_EMPTY"
BOUNDING_BOXES_INVALID = "BOUNDING_BOXES_INVALID"
CONTENT_HASH_MISSING = "CONTENT_HASH_MISSING"


@dataclass(frozen=True)
class ChunkValidationErrorItem:
    """Single validation error with code and offending LDU ids. Spec 04 §6.2; spec 07 §5.4."""

    code: str
    ldu_ids: list[str] = field(default_factory=list)
    message: str | None = None

    def __str__(self) -> str:
        part = f"{self.code}"
        if self.ldu_ids:
            part += f" (ldu_ids={self.ldu_ids!r})"
        if self.message:
            part += f": {self.message}"
        return part


@dataclass
class ValidationResult:
    """Result of validating a list of LDUs. Fail loudly with clear error codes."""

    success: bool = True
    errors: list[ChunkValidationErrorItem] = field(default_factory=list)
    ldus: list[LDU] | None = None

    def __post_init__(self) -> None:
        if not self.success and not self.errors:
            self.errors = [
                ChunkValidationErrorItem(
                    code="VALIDATION_FAILED",
                    message="Validation failed with no error messages.",
                )
            ]

    def error_messages(self) -> list[str]:
        """Human-readable list of error strings (for logging/backward compat)."""
        return [str(e) for e in self.errors]


class ChunkValidationError(Exception):
    """Raised when ChunkValidator rejects the LDU list. Contains ValidationResult with structured errors."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__("; ".join(result.error_messages()))


class ChunkValidator:
    """
    Enforces the 5 chunking rules as hard constraints per spec 04 §6.
    Rejects: split table header/body, standalone caption, figure without caption,
    list split mid-item, missing parent_section after section header,
    missing page_refs/bbox/content_hash. Preserves provenance: does not modify LDUs.
    """

    def __init__(self, *, reject_missing_parent_section: bool = True) -> None:
        """
        reject_missing_parent_section: If True (default), R4 is a hard constraint.
        If False, missing parent_section is only logged (spec 04: configurable).
        """
        self.reject_missing_parent_section = reject_missing_parent_section

    def validate(self, ldus: list[LDU]) -> ValidationResult:
        """
        Run all checks. Returns ValidationResult with success=True and ldus if valid;
        otherwise success=False and errors list with error codes and ldu_ids.
        """
        errors: list[ChunkValidationErrorItem] = []
        if not ldus:
            return ValidationResult(success=True, errors=[], ldus=[])

        # --- Provenance (mandatory) ---
        for i, ldu in enumerate(ldus):
            if not ldu.page_refs:
                errors.append(
                    ChunkValidationErrorItem(
                        code=PAGE_REFS_EMPTY,
                        ldu_ids=[ldu.id],
                        message=f"LDU[{i}] id={ldu.id!r}: page_refs must be non-empty (missing provenance).",
                    )
                )
            if not ldu.bounding_boxes:
                errors.append(
                    ChunkValidationErrorItem(
                        code=BOUNDING_BOXES_INVALID,
                        ldu_ids=[ldu.id],
                        message=f"LDU[{i}] id={ldu.id!r}: bounding_boxes must be non-empty (missing provenance).",
                    )
                )
            if not (ldu.content_hash or "").strip():
                errors.append(
                    ChunkValidationErrorItem(
                        code=CONTENT_HASH_MISSING,
                        ldu_ids=[ldu.id],
                        message=f"LDU[{i}] id={ldu.id!r}: content_hash must be non-empty.",
                    )
                )

        # --- R1: No table split (header in one LDU, body in another without header) ---
        table_types = (LDUContentType.TABLE, LDUContentType.TABLE_SECTION)
        for i in range(len(ldus) - 1):
            a, b = ldus[i], ldus[i + 1]
            if a.content_type not in table_types or b.content_type not in table_types:
                continue
            header_only = _table_has_header_only(a)
            body_only = _table_has_body_only(b)
            if header_only and body_only:
                errors.append(
                    ChunkValidationErrorItem(
                        code=TABLE_HEADER_CELLS_SPLIT,
                        ldu_ids=[a.id, b.id],
                        message=(
                            f"Table split across LDUs: {a.id!r} has header only; {b.id!r} has rows only. "
                            "Each table part must include the header row."
                        ),
                    )
                )
        # Reject a single table LDU whose content (text) is data-only (no header row)
        for ldu in ldus:
            if ldu.content_type in table_types and _table_content_is_data_only(ldu):
                errors.append(
                    ChunkValidationErrorItem(
                        code=TABLE_HEADER_CELLS_SPLIT,
                        ldu_ids=[ldu.id],
                        message=f"Table LDU {ldu.id!r} content has data rows without header row.",
                    )
                )

        # --- R2: Figure + caption unity ---
        for i, ldu in enumerate(ldus):
            if ldu.content_type == LDUContentType.CAPTION:
                errors.append(
                    ChunkValidationErrorItem(
                        code=FIGURE_CAPTION_NOT_UNIFIED,
                        ldu_ids=[ldu.id],
                        message=f"Standalone caption LDU[{i}] id={ldu.id!r}. Caption must be merged into figure/table LDU.",
                    )
                )
            elif ldu.content_type == LDUContentType.FIGURE:
                has_caption = (
                    (ldu.text or "").strip()
                    or (ldu.raw_payload or {}).get("caption")
                    or (ldu.raw_payload or {}).get("caption_text")
                )
                if not has_caption:
                    errors.append(
                        ChunkValidationErrorItem(
                            code=FIGURE_CAPTION_NOT_UNIFIED,
                            ldu_ids=[ldu.id],
                            message=f"Figure LDU[{i}] id={ldu.id!r} has no caption. Figure and caption must be in the same LDU.",
                        )
                    )

        # --- R3: List integrity (no mid-item split) ---
        for i, ldu in enumerate(ldus):
            if ldu.content_type != LDUContentType.LIST:
                continue
            if ldu.raw_payload.get("list_complete") is False:
                errors.append(
                    ChunkValidationErrorItem(
                        code=LIST_MID_ITEM_SPLIT,
                        ldu_ids=[ldu.id],
                        message=f"List LDU[{i}] id={ldu.id!r} is split mid-item (list_complete=False).",
                    )
                )
            if _list_text_ends_mid_item(ldu.text):
                errors.append(
                    ChunkValidationErrorItem(
                        code=LIST_MID_ITEM_SPLIT,
                        ldu_ids=[ldu.id],
                        message=f"List LDU[{i}] id={ldu.id!r} text ends with incomplete list item.",
                    )
                )

        # --- R4: Section headers as parent metadata ---
        current_section_ldu_id: str | None = None
        for i, ldu in enumerate(ldus):
            if ldu.content_type in (
                LDUContentType.SECTION_INTRO,
                LDUContentType.SECTION_HEADER,
                LDUContentType.HEADING,
            ):
                current_section_ldu_id = ldu.id
                continue
            if (
                self.reject_missing_parent_section
                and current_section_ldu_id is not None
                and (ldu.parent_section_id is None or ldu.parent_section_id == "")
            ):
                errors.append(
                    ChunkValidationErrorItem(
                        code=PARENT_SECTION_MISSING,
                        ldu_ids=[ldu.id],
                        message=(
                            f"LDU[{i}] id={ldu.id!r} has no parent_section_id. "
                            f"Section header (LDU {current_section_ldu_id!r}) exists; content must have parent_section_id set."
                        ),
                    )
                )

        # R5 (cross-references) is best-effort; no rejection.

        if errors:
            return ValidationResult(success=False, errors=errors, ldus=None)
        return ValidationResult(success=True, errors=[], ldus=ldus)

    def validate_or_raise(self, ldus: list[LDU]) -> list[LDU]:
        """Run validate(); on failure raise ChunkValidationError with clear error codes."""
        result = self.validate(ldus)
        if not result.success:
            raise ChunkValidationError(result)
        return result.ldus or []


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


def _table_content_is_data_only(ldu: LDU) -> bool:
    """True if table LDU content (text) has first line that looks like data only (no header)."""
    text = (ldu.text or "").strip()
    if not text:
        return False
    lines = text.split("\n")
    if not lines:
        return False
    first_line = lines[0].strip()
    if not first_line:
        return False
    # Header row typically has at least one alphabetic token; data row may be all numeric/codes
    cells = first_line.replace("\t", " ").split()
    if not cells:
        return False
    return not any(c and any(ch.isalpha() for ch in c) for c in cells)


def _list_text_ends_mid_item(text: str) -> bool:
    """Heuristic: text ends with incomplete list item (mid-sentence or trailing space)."""
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
    # Last line looks like "3." or "3. Incomplete" without sentence terminator
    if last[0].isdigit() and "." in last[:4]:
        rest = last.split(".", 1)[-1].strip()
        if not rest or len(rest) < 2:
            return True
        if not rest.endswith((".", "!", "?")):
            return True
    return False
