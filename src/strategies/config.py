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
            "confidence_threshold": 0.5,
            "min_chars_per_page": 50,
            "max_image_area_ratio": 0.5,
            "min_char_density_per_10k_points2": 1.0,
        }
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("fast_text") or {
        "confidence_threshold": 0.5,
        "min_chars_per_page": 50,
        "max_image_area_ratio": 0.5,
        "min_char_density_per_10k_points2": 1.0,
    }
