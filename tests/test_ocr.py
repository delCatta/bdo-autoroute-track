"""Tests for distance parsing and crop preprocessing."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from bdo_tracker.ocr import Reading, parse_distance, preprocess

MIN_M = 0.0
MAX_M = 20000.0


def parse(text: str) -> float | None:
    return parse_distance(text, MIN_M, MAX_M)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3970", 3970.0),
        ("3,970", 3970.0),          # thousands separator is decoration here
        ("450m", 450.0),
        ("450 m", 450.0),
        ("1.2km", 1200.0),          # km makes the dot a real decimal
        ("2km", 2000.0),
        ("  8421  ", 8421.0),
        ("0", 0.0),
    ],
)
def test_parses_expected_forms(text: str, expected: float) -> None:
    assert parse(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "-", "<ocr error: boom>"])
def test_returns_none_when_there_is_no_number(text: str) -> None:
    assert parse(text) is None


def test_prefers_the_number_nearest_the_icon() -> None:
    """The crop is icon-anchored and extends left, so right-most is the real one.

    Stray UI text can drift into the widened left edge of the box.
    """
    assert parse("27 3970") == 3970.0


def test_left_preference_is_available() -> None:
    assert parse_distance("27 3970", MIN_M, MAX_M, prefer="left") == 27.0


def test_rejects_readings_outside_the_valid_range() -> None:
    assert parse_distance("999999", MIN_M, MAX_M) is None
    # ...but still finds a valid number elsewhere in the same string.
    assert parse_distance("999999 4200", MIN_M, MAX_M) == 4200.0
    assert parse_distance("4200 999999", MIN_M, MAX_M) == 4200.0


def test_preprocess_makes_bright_glyphs_black_on_white() -> None:
    # Mimic the readout: a dark background with a bright glyph blob.
    arr = np.full((20, 60), 30, dtype=np.uint8)
    arr[5:15, 10:50] = 230
    prepared = preprocess(Image.fromarray(arr, mode="L"), upscale=2, brightness_threshold=150)

    out = np.asarray(prepared)
    assert set(np.unique(out)) <= {0, 255}
    assert 0 in np.unique(out)      # the glyph became black
    assert out[0, 0] == 255         # the padding is white
    # 20x60 upscaled 2x, plus 12px padding on every side.
    assert prepared.size == (60 * 2 + 24, 20 * 2 + 24)


def test_preprocess_drops_dim_background_texture() -> None:
    """Background noise below the threshold must not survive as text."""
    arr = np.full((20, 60), 120, dtype=np.uint8)  # noisy but below threshold
    prepared = preprocess(Image.fromarray(arr, mode="L"), upscale=1, brightness_threshold=150)
    assert np.asarray(prepared).min() == 255  # nothing was kept


def test_reading_ok_reflects_whether_a_number_was_found() -> None:
    assert Reading(meters=3970.0, raw_text="3970").ok
    assert not Reading(meters=None, raw_text="").ok
