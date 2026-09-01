"""Observation: what one look at the screen amounts to."""

from __future__ import annotations

import pytest
from PIL import Image

from bdo_autoroute.marker import Box, Sighting
from bdo_autoroute.observation import (
    LOW_CONFIDENCE,
    NO_MARKER,
    ORDINARY,
    RED,
    UNPARSED,
    Observation,
)
from bdo_autoroute.readout import Reading

THRESHOLD = 0.85


def frame(size=(200, 100)) -> Image.Image:
    return Image.new("RGB", size, (20, 20, 30))


def sighting(confidence=0.99, digits=Box(10, 10, 60, 14)) -> Sighting:
    return Sighting(confidence=confidence, icon=Box(80, 10, 17, 16), digits=digits)


class TestCategory:
    def test_category_is_no_marker_when_nothing_matched(self):
        assert Observation(frame()).category(THRESHOLD) == NO_MARKER

    def test_category_is_unparsed_when_the_digits_could_not_be_read(self):
        seen = Observation(frame(), sighting(), Reading(None, "???"))
        assert seen.category(THRESHOLD) == UNPARSED

    def test_category_is_unparsed_when_the_digits_are_off_screen(self):
        edge = Observation(frame(), sighting(digits=Box(0, 0, 0, 0)))
        assert edge.category(THRESHOLD) == UNPARSED

    def test_category_is_low_confidence_near_the_threshold(self):
        seen = Observation(frame(), sighting(confidence=0.86), Reading(500.0, "500"))
        assert seen.category(THRESHOLD) == LOW_CONFIDENCE

    def test_category_is_red_when_the_readout_turned_red(self):
        seen = Observation(frame(), sighting(), Reading(90.0, "90", red_ratio=0.9))
        assert seen.category(THRESHOLD) == RED

    def test_category_is_ordinary_for_a_clean_read(self):
        seen = Observation(frame(), sighting(), Reading(500.0, "500"))
        assert seen.category(THRESHOLD) == ORDINARY

    def test_category_prefers_the_more_instructive_failure(self):
        marginal = Observation(frame(), sighting(confidence=0.86), Reading(None, ""))
        assert marginal.category(THRESHOLD) == UNPARSED


class TestRawText:
    def test_raw_text_explains_a_missing_marker(self):
        assert Observation(frame()).raw_text == "<marker not found>"

    def test_raw_text_explains_digits_off_the_screen_edge(self):
        edge = Observation(frame(), sighting(digits=Box(0, 0, 0, 0)))
        assert "screen edge" in edge.raw_text

    def test_raw_text_returns_what_ocr_saw(self):
        seen = Observation(frame(), sighting(), Reading(500.0, "5OO"))
        assert seen.raw_text == "5OO"


class TestSample:
    def test_sample_returns_the_whole_frame_when_no_marker_was_found(self):
        assert Observation(frame()).sample(NO_MARKER).size == (200, 100)

    def test_sample_returns_just_the_digits_when_there_are_some(self):
        seen = Observation(frame(), sighting(), Reading(500.0, "500"))
        assert seen.sample(ORDINARY).size == (60, 14)


class TestProperties:
    def test_distance_is_none_without_a_reading(self):
        assert Observation(frame()).distance is None

    def test_confidence_is_zero_without_a_sighting(self):
        assert Observation(frame()).confidence == 0.0

    @pytest.mark.parametrize(("ratio", "expected"), [(0.0, False), (0.9, True)])
    def test_near_indicator_follows_the_reading(self, ratio, expected):
        seen = Observation(frame(), sighting(), Reading(90.0, "90", ratio))
        assert seen.near_indicator is expected


class TestAsMetadata:
    def test_as_metadata_records_everything_known_about_the_poll(self):
        seen = Observation(frame(), sighting(), Reading(500.0, "500", 0.1))
        recorded = seen.as_metadata(THRESHOLD)

        assert recorded["meters"] == 500.0
        assert recorded["raw_ocr"] == "500"
        assert recorded["match_threshold"] == THRESHOLD
        assert recorded["digits_box"] == [10, 10, 60, 14]

    def test_as_metadata_survives_a_missing_marker(self):
        recorded = Observation(frame()).as_metadata(THRESHOLD)
        assert recorded["icon_box"] is None
        assert recorded["meters"] is None
