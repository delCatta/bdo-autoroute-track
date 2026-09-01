"""Readout: turning a crop of the marker into a number.

The misread cases here are real ones seen against the live game; .claude/CONTEXT.md
sections 5 and 7 record where each came from.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from bdo_autoroute.readout import RED_RATIO, Glyphs, Reading, distance_in, value_channel

WHITE_TEXT = (232, 230, 220)
RED_TEXT = (226, 62, 48)
BACKGROUND = (18, 20, 26)
THRESHOLD = 120


def swatch(colour, size=(40, 16)) -> Image.Image:
    pixels = np.full((size[1], size[0], 3), BACKGROUND, dtype=np.uint8)
    pixels[4:12, 6:34] = colour
    return Image.fromarray(pixels, mode="RGB")


def glyphs(crop: Image.Image, upscale: int = 2) -> Glyphs:
    return Glyphs(crop, threshold=THRESHOLD, upscale=upscale)


def metres(text: str, prefer: str = "longest") -> float | None:
    return distance_in(text, floor=0.0, ceiling=20000.0, prefer=prefer)


class TestDistanceIn:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("3970", 3970.0),
            ("3,970", 3970.0),
            ("450m", 450.0),
            ("450 m", 450.0),
            ("1.2km", 1200.0),
            ("2km", 2000.0),
            ("  8421  ", 8421.0),
            ("0", 0.0),
        ],
    )
    def test_distance_in_reads_the_forms_the_game_draws(self, text, expected):
        assert metres(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["", "   ", "abc", "-", "<ocr error: boom>"])
    def test_distance_in_returns_none_without_a_number(self, text):
        assert metres(text) is None

    def test_distance_in_reads_the_apostrophe_misread_of_1169(self):
        assert metres("11'69 9") == 1169.0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("11'69", 1169.0), ("3`970", 3970.0), ("3’970", 3970.0), ("1´234", 1234.0)],
    )
    def test_distance_in_joins_separator_split_digits(self, text, expected):
        assert metres(text) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("11'69 9", 1169.0), ("9 1169", 1169.0), ("27 3970", 3970.0), ("1241.0 10", 12410.0)],
    )
    def test_distance_in_prefers_the_longest_run_over_stray_fragments(self, text, expected):
        assert metres(text) == expected

    def test_distance_in_breaks_ties_toward_the_icon(self):
        assert metres("111 222") == 222.0

    def test_distance_in_rejects_values_outside_the_valid_range(self):
        assert metres("999999") is None
        assert metres("999999 4200") == 4200.0

    def test_distance_in_honours_an_explicit_preference(self):
        assert metres("27 3970", prefer="left") == 27.0
        assert metres("27 3970", prefer="right") == 3970.0


class TestValueChannel:
    def test_value_channel_keeps_red_that_luminance_would_lose(self):
        red = Image.new("RGB", (4, 4), RED_TEXT)
        assert np.asarray(red.convert("L")).max() < THRESHOLD
        assert value_channel(red).max() >= THRESHOLD


class TestStencil:
    @pytest.mark.parametrize("colour", [WHITE_TEXT, RED_TEXT])
    def test_stencil_keeps_glyphs_of_either_colour(self, colour):
        assert (np.asarray(glyphs(swatch(colour)).stencil) == 0).any()

    def test_stencil_drops_the_dark_background(self):
        flat = Image.new("RGB", (40, 16), BACKGROUND)
        assert np.asarray(glyphs(flat, upscale=1).stencil).min() == 255

    def test_stencil_pads_around_the_glyphs(self):
        stencil = glyphs(swatch(WHITE_TEXT)).stencil
        assert stencil.size == (40 * 2 + 24, 16 * 2 + 24)
        assert np.asarray(stencil)[0, 0] == 255


class TestRedness:
    def test_redness_separates_red_text_from_white(self):
        assert glyphs(swatch(WHITE_TEXT)).redness < RED_RATIO
        assert glyphs(swatch(RED_TEXT)).redness >= RED_RATIO

    def test_redness_is_zero_when_nothing_is_lit(self):
        assert glyphs(Image.new("RGB", (20, 10), BACKGROUND)).redness == 0.0


class TestReading:
    def test_understood_reflects_whether_a_number_was_found(self):
        assert Reading(3970.0, "3970").understood
        assert not Reading(None, "").understood

    @pytest.mark.parametrize(
        ("ratio", "expected"), [(0.0, False), (0.2, False), (RED_RATIO, True), (0.9, True)]
    )
    def test_near_indicator_follows_the_red_ratio(self, ratio, expected):
        assert Reading(90.0, "90", ratio).near_indicator is expected
