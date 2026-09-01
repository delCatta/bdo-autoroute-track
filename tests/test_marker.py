"""Marker: finding the route icon and the digits beside it."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from bdo_autoroute.marker import ICON_CLEARANCE_PX, Box, Marker, MarkerError, Offset

ICON_SIZE = 16


def icon() -> Image.Image:
    pixels = np.full((ICON_SIZE, ICON_SIZE, 3), (180, 40, 120), dtype=np.uint8)
    pixels[4:12, 4:12] = (250, 250, 250)
    pixels[6:10, 6:10] = (120, 20, 90)
    return Image.fromarray(pixels, mode="RGB")


def frame_with(sprite: Image.Image, at: tuple[int, int], size=(800, 400)) -> Image.Image:
    noise = np.random.default_rng(seed=7).integers(0, 60, (size[1], size[0], 3), dtype=np.uint8)
    frame = Image.fromarray(noise, mode="RGB")
    frame.paste(sprite, at)
    return frame


def offset() -> Offset:
    return Offset(-64, 0, 60, ICON_SIZE)


def marker(**overrides) -> Marker:
    settings = {"match_threshold": 0.7}
    settings.update(overrides)
    return Marker(icon(), offset(), **settings)


class TestSighting:
    @pytest.mark.parametrize("position", [(100, 100), (400, 250), (700, 40), (64, 0)])
    def test_sighting_finds_the_icon_wherever_it_sits(self, position):
        found = marker().sighting(frame_with(icon(), position))
        assert found is not None
        assert found.icon.origin == position
        assert found.confidence > 0.9

    def test_sighting_moves_the_digits_box_with_the_icon(self):
        watcher = marker()
        first = watcher.sighting(frame_with(icon(), (300, 200)))
        second = watcher.sighting(frame_with(icon(), (500, 260)))
        assert second.digits.left - first.digits.left == 200
        assert second.digits.top - first.digits.top == 60

    def test_sighting_returns_none_when_the_marker_is_absent(self):
        noise = np.random.default_rng(seed=3).integers(0, 60, (400, 800, 3), dtype=np.uint8)
        assert marker(match_threshold=0.9).sighting(Image.fromarray(noise, "RGB")) is None

    def test_sighting_keeps_the_digits_box_inside_the_frame(self):
        frame = frame_with(icon(), (10, 100))
        digits = marker().sighting(frame).digits
        assert digits.left >= 0 and digits.top >= 0
        assert digits.left + digits.width <= frame.width
        assert digits.top + digits.height <= frame.height

    def test_sighting_covers_the_digits(self):
        frame = frame_with(icon(), (400, 200))
        bar = Image.fromarray(np.full((ICON_SIZE, 60, 3), 240, dtype=np.uint8), "RGB")
        frame.paste(bar, (400 - 64, 200))
        crop = marker().sighting(frame).digits.crop(frame)
        assert np.asarray(crop.convert("L")).mean() > 200

    def test_sighting_scales_template_and_offset_together(self):
        watcher = Marker(icon(), offset(), match_threshold=0.6, scale=2.0)
        assert watcher.icon_size == (ICON_SIZE * 2, ICON_SIZE * 2)

        bigger = icon().resize((ICON_SIZE * 2, ICON_SIZE * 2), Image.LANCZOS)
        found = watcher.sighting(frame_with(bigger, (300, 150), size=(1600, 800)))
        assert found.digits.left == 300 - 128
        assert found.digits.width == 120

    def test_sighting_raises_when_the_frame_is_smaller_than_the_icon(self):
        with pytest.raises(MarkerError):
            marker().sighting(Image.new("RGB", (8, 8)))


class TestReadable:
    def test_readable_is_false_when_the_digits_fall_off_screen(self):
        found = marker().sighting(frame_with(icon(), (0, 0)))
        assert found is not None
        assert found.confidence > 0.9
        assert not found.readable

    def test_readable_is_true_for_an_ordinary_placement(self):
        assert marker().sighting(frame_with(icon(), (300, 150))).readable


class TestConfidenceIn:
    def test_confidence_in_separates_the_marker_from_scenery(self):
        watcher = marker(match_threshold=0.85)
        present = watcher.confidence_in(frame_with(icon(), (300, 150)))
        noise = np.random.default_rng(seed=11).integers(0, 60, (400, 800, 3), dtype=np.uint8)
        absent = watcher.confidence_in(Image.fromarray(noise, "RGB"))

        assert present > 0.95
        assert absent < 0.85 <= present


class TestOffsetBetween:
    def test_between_places_the_box_relative_to_the_icon(self):
        derived = Offset.between(Box(100, 50, 40, 18), Box(150, 48, 16, 16), left_slack=0.0)
        assert derived.left == 100 - 150
        assert derived.height > 18

    def test_between_grows_the_box_leftward_by_the_slack(self):
        derived = Offset.between(Box(100, 50, 40, 18), Box(150, 48, 16, 16), left_slack=2.0)
        assert derived.left == (100 - 80) - 150
        assert derived.width >= 40 + 80

    def test_between_reaches_to_just_short_of_the_icon(self):
        derived = Offset.between(Box(100, 50, 40, 18), Box(157, 48, 16, 16), left_slack=2.0)
        assert derived.left + derived.width == -ICON_CLEARANCE_PX

    def test_between_covers_a_number_far_longer_than_the_calibrated_one(self):
        derived = Offset.between(Box(1633, 1183, 23, 10), Box(1673, 1181, 17, 16), left_slack=2.0)

        icon_left, pitch = 1766, 23 / 3
        number_right = icon_left - 8
        number_left = number_right - round(pitch * 5)

        assert icon_left + derived.left <= number_left
        assert icon_left + derived.left + derived.width >= number_right


class TestIconSize:
    def test_marker_rejects_a_template_too_small_to_match(self):
        with pytest.raises(MarkerError):
            Marker(Image.new("RGB", (2, 2)), offset())


class TestBox:
    def test_empty_is_true_for_a_zero_sized_box(self):
        assert Box(0, 0, 0, 10).empty
        assert not Box(0, 0, 10, 10).empty

    def test_clamped_to_keeps_the_box_within_bounds(self):
        clamped = Box(-20, -5, 60, 40).clamped_to((100, 100))
        assert (clamped.left, clamped.top) == (0, 0)
        assert clamped.width == 40 and clamped.height == 35
