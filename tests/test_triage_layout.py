# Unit tests for layout_complexity detection (P1-T004). Signal logic with mocked outputs.

import pytest
from pathlib import Path

from src.agents.triage import (
    compute_layout_from_signals,
    detect_layout_complexity,
    load_layout_config,
)
from src.models import LayoutComplexity


# -----------------------------------------------------------------------------
# Config loading
# -----------------------------------------------------------------------------


def test_load_layout_config_returns_dict():
    """Layout config loader returns a dict with expected keys or defaults."""
    config = load_layout_config()
    assert isinstance(config, dict)


def test_load_layout_config_nonexistent_uses_defaults():
    """When config file does not exist, built-in layout defaults are used."""
    config = load_layout_config(Path("/nonexistent/rubric/extraction_rules.yaml"))
    assert config.get("table_area_ratio_heavy") == 0.25
    assert config.get("figure_area_ratio_heavy") == 0.4


# -----------------------------------------------------------------------------
# compute_layout_from_signals (mocked signals)
# -----------------------------------------------------------------------------


def test_layout_single_column_low_table_figure():
    """Single text column, no significant table/figure area → single_column."""
    signals = {
        "table_area_ratio_per_page": [0.05, 0.02],
        "table_regions_per_page": [0, 0],
        "image_area_ratio_per_page": [0.05, 0.1],
        "columns_per_page": [1, 1],
    }
    config = {
        "table_area_ratio_heavy": 0.25,
        "table_regions_per_page_heavy": 2,
        "figure_area_ratio_heavy": 0.4,
    }
    layout, confidence, meta = compute_layout_from_signals(signals, config)
    assert layout == LayoutComplexity.SINGLE_COLUMN
    assert meta.get("reason") == "single_column_low_table_figure"


def test_layout_multi_column_heuristic():
    """Two or more columns (heuristic) → multi_column."""
    signals = {
        "table_area_ratio_per_page": [0.05],
        "table_regions_per_page": [0],
        "image_area_ratio_per_page": [0.1],
        "columns_per_page": [2],
    }
    config = {"table_area_ratio_heavy": 0.25, "figure_area_ratio_heavy": 0.4}
    layout, confidence, meta = compute_layout_from_signals(signals, config)
    assert layout == LayoutComplexity.MULTI_COLUMN
    assert meta.get("max_columns") == 2


def test_layout_table_heavy_above_threshold():
    """Table area ratio above configured threshold → table_heavy."""
    signals = {
        "table_area_ratio_per_page": [0.35, 0.30],
        "table_regions_per_page": [1, 2],
        "image_area_ratio_per_page": [0.1, 0.1],
        "columns_per_page": [1, 1],
    }
    config = {
        "table_area_ratio_heavy": 0.25,
        "table_regions_per_page_heavy": 2,
        "figure_area_ratio_heavy": 0.4,
    }
    layout, confidence, meta = compute_layout_from_signals(signals, config)
    assert layout == LayoutComplexity.TABLE_HEAVY
    assert meta.get("mean_table_area_ratio") >= 0.25


def test_layout_table_regions_above_threshold():
    """Table regions per page above threshold → table_heavy."""
    signals = {
        "table_area_ratio_per_page": [0.1],
        "table_regions_per_page": [3],
        "image_area_ratio_per_page": [0.1],
        "columns_per_page": [1],
    }
    config = {"table_area_ratio_heavy": 0.25, "table_regions_per_page_heavy": 2}
    layout, _, meta = compute_layout_from_signals(signals, config)
    assert layout == LayoutComplexity.TABLE_HEAVY
    assert meta.get("mean_table_regions_per_page") == 3


def test_layout_figure_heavy():
    """Figure/image area above threshold → figure_heavy."""
    signals = {
        "table_area_ratio_per_page": [0.05],
        "table_regions_per_page": [0],
        "image_area_ratio_per_page": [0.5],
        "columns_per_page": [1],
    }
    config = {"table_area_ratio_heavy": 0.25, "figure_area_ratio_heavy": 0.4}
    layout, confidence, meta = compute_layout_from_signals(signals, config)
    assert layout == LayoutComplexity.FIGURE_HEAVY


def test_layout_both_table_and_figure_heavy_mixed():
    """Both table and figure ratios high → mixed (dominance rule)."""
    signals = {
        "table_area_ratio_per_page": [0.35],
        "table_regions_per_page": [2],
        "image_area_ratio_per_page": [0.5],
        "columns_per_page": [1],
    }
    config = {"table_area_ratio_heavy": 0.25, "figure_area_ratio_heavy": 0.4}
    layout, confidence, meta = compute_layout_from_signals(signals, config)
    assert layout == LayoutComplexity.MIXED
    assert meta.get("reason") == "both_table_and_figure_heavy"


def test_layout_config_threshold_changes_outcome():
    """Changing table_area_ratio_heavy in config changes outcome for borderline signals."""
    signals = {
        "table_area_ratio_per_page": [0.30, 0.30],
        "table_regions_per_page": [0, 0],
        "image_area_ratio_per_page": [0.0, 0.0],
        "columns_per_page": [1, 1],
    }
    config_low = {"table_area_ratio_heavy": 0.35, "figure_area_ratio_heavy": 0.4}
    config_high = {"table_area_ratio_heavy": 0.25, "figure_area_ratio_heavy": 0.4}

    layout_low, _, _ = compute_layout_from_signals(signals, config_low)
    layout_high, _, _ = compute_layout_from_signals(signals, config_high)

    assert layout_low == LayoutComplexity.SINGLE_COLUMN
    assert layout_high == LayoutComplexity.TABLE_HEAVY


def test_layout_detect_with_injected_signals():
    """detect_layout_complexity with signals=... skips PDF and uses provided signals."""
    signals = {
        "table_area_ratio_per_page": [0.5],
        "table_regions_per_page": [1],
        "image_area_ratio_per_page": [0.1],
        "columns_per_page": [1],
    }
    layout, confidence, meta = detect_layout_complexity(Path("/any/path.pdf"), signals=signals)
    assert layout == LayoutComplexity.TABLE_HEAVY
    assert "mean_table_area_ratio" in meta
