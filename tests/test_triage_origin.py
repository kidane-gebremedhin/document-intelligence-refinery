# Unit tests for origin_type detection (P1-T003). Signal logic with mocked extractor outputs.

import pytest
from pathlib import Path

from src.agents.triage import (
    compute_origin_from_signals,
    detect_origin_type,
    load_origin_config,
)
from src.models import OriginType


# -----------------------------------------------------------------------------
# Config loading
# -----------------------------------------------------------------------------


def test_load_origin_config_returns_dict():
    """Config loader returns a dict with expected keys (or defaults)."""
    config = load_origin_config()
    assert isinstance(config, dict)
    assert "min_chars_per_page_digital" in config or config == {}


def test_load_origin_config_nonexistent_uses_defaults():
    """When config file does not exist, built-in defaults are used."""
    config = load_origin_config(Path("/nonexistent/rubric/extraction_rules.yaml"))
    assert config.get("min_chars_per_page_digital") == 50
    assert config.get("max_image_area_ratio_digital") == 0.5


# -----------------------------------------------------------------------------
# compute_origin_from_signals (no PDF; mocked signals)
# -----------------------------------------------------------------------------


def test_origin_all_pages_zero_chars_scanned_image():
    """Zero character count on all pages → scanned_image."""
    signals = {
        "chars_per_page": [0, 0, 0],
        "image_area_ratio_per_page": [0.0, 0.0, 0.0],
        "form_fillable": False,
    }
    config = {"min_chars_per_page_digital": 50, "max_image_area_ratio_digital": 0.5}
    origin, confidence, meta = compute_origin_from_signals(signals, config)
    assert origin == OriginType.SCANNED_IMAGE
    assert 0 <= confidence <= 1
    assert "reason" in meta


def test_origin_high_chars_low_image_native_digital():
    """High character count and low image area → native_digital."""
    signals = {
        "chars_per_page": [500, 600, 400],
        "image_area_ratio_per_page": [0.05, 0.1, 0.0],
        "form_fillable": False,
    }
    config = {
        "min_chars_per_page_digital": 50,
        "max_image_area_ratio_digital": 0.5,
        "fraction_pages_digital_max": 0.9,
    }
    origin, confidence, meta = compute_origin_from_signals(signals, config)
    assert origin == OriginType.NATIVE_DIGITAL
    assert meta.get("fraction_pages_digital") == 1.0


def test_origin_fraction_pages_digital_mixed():
    """Only a fraction of pages above min chars → mixed."""
    signals = {
        "chars_per_page": [500, 0, 0, 600, 0],
        "image_area_ratio_per_page": [0.0] * 5,
        "form_fillable": False,
    }
    config = {
        "min_chars_per_page_digital": 50,
        "max_image_area_ratio_digital": 0.5,
        "fraction_pages_digital_min": 0.1,
        "fraction_pages_digital_max": 0.9,
    }
    origin, confidence, meta = compute_origin_from_signals(signals, config)
    assert origin == OriginType.MIXED
    assert 0 < meta.get("fraction_pages_digital", 0) < 1


def test_origin_zero_pages_scanned():
    """Zero pages → scanned_image (edge case)."""
    signals = {
        "chars_per_page": [],
        "image_area_ratio_per_page": [],
        "form_fillable": False,
    }
    config = {"min_chars_per_page_digital": 50}
    origin, confidence, meta = compute_origin_from_signals(signals, config)
    assert origin == OriginType.SCANNED_IMAGE
    assert meta.get("reason") == "zero_pages"


def test_origin_detect_with_injected_signals():
    """detect_origin_type with signals=... skips PDF and uses provided signals."""
    signals = {
        "chars_per_page": [0, 0],
        "image_area_ratio_per_page": [0.0, 0.0],
        "form_fillable": False,
    }
    origin, confidence, meta = detect_origin_type(Path("/any/path.pdf"), signals=signals)
    assert origin == OriginType.SCANNED_IMAGE
    assert "chars_per_page" in meta


def test_origin_config_threshold_changes_outcome():
    """Changing min_chars_per_page_digital in config changes outcome for borderline signals."""
    # With min_chars=50, 40 chars per page is "below digital"
    signals = {
        "chars_per_page": [40, 40],
        "image_area_ratio_per_page": [0.0, 0.0],
        "form_fillable": False,
    }
    config_low = {"min_chars_per_page_digital": 30, "fraction_pages_digital_max": 0.9}
    config_high = {"min_chars_per_page_digital": 50, "fraction_pages_digital_max": 0.9}

    origin_low, _, _ = compute_origin_from_signals(signals, config_low)
    origin_high, _, _ = compute_origin_from_signals(signals, config_high)

    assert origin_low == OriginType.NATIVE_DIGITAL
    assert origin_high == OriginType.SCANNED_IMAGE
