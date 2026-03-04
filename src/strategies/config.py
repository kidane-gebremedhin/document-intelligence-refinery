# Load extraction rules for strategies (config-over-code). Same file as triage: rubric/extraction_rules.yaml.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "rubric" / "extraction_rules.yaml"


def load_fast_text_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load fast_text section from extraction_rules.yaml. Used by FastTextExtractor."""
    path = config_path or _DEFAULT_RULES_PATH
    if not path.exists():
        logger.warning("Config not found at %s; using built-in defaults", path)
        return {
            "backend": "pdfplumber",
            "confidence_threshold": 0.5,
            "min_chars_per_page": 50,
            "max_image_area_ratio": 0.5,
            "min_char_density_per_10k_points2": 1.0,
        }
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("fast_text") or {
        "backend": "pdfplumber",
        "confidence_threshold": 0.5,
        "min_chars_per_page": 50,
        "max_image_area_ratio": 0.5,
        "min_char_density_per_10k_points2": 1.0,
    }


def load_layout_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load layout section from extraction_rules.yaml. Used by LayoutExtractor. Backend must be mineru or docling."""
    path = config_path or _DEFAULT_RULES_PATH
    if not path.exists():
        return {"backend": "docling", "confidence_default": 0.75, "first_row_as_header": True}
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("layout") or {"backend": "docling", "confidence_default": 0.75, "first_row_as_header": True}


def load_vision_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load vision section from extraction_rules.yaml. Used by VisionExtractor."""
    path = config_path or _DEFAULT_RULES_PATH
    if not path.exists():
        return {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
            "max_pages_per_document": 50,
            "confidence_default": 0.8,
        }
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("vision") or {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "max_pages_per_document": 50,
        "confidence_default": 0.8,
    }
