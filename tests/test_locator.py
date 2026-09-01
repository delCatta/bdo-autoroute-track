"""Tests for finding the world-anchored route marker.

The marker moves with the camera, so the whole point is that the digits box is
derived from wherever the icon is found rather than from fixed coordinates.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from bdo_tracker.locator import (
    ICON_CLEARANCE_PX,
    LocatorError,
    MarkerLocator,
    digits_offset_from_boxes,
)

ICON_W, ICON_H = 16, 16


def make_icon() -> Image.Image:
    """A distinctive coloured sprite, like the magenta route icon."""
    arr = np.zeros((ICON_H, ICON_W, 3), dtype=np.uint8)
    arr[:, :] = (180, 40, 120)
    arr[4:12, 4:12] = (250, 250, 250)
    arr[6:10, 6:10] = (120, 20, 90)
    return Image.fromarray(arr, mode="RGB")


def make_frame(icon: Image.Image, at: tuple[int, int], size=(800, 400)) -> Image.Image:
    """A noisy frame with the icon pasted at a known position."""
    rng = np.random.default_rng(seed=7)
    bg = rng.integers(0, 60, size=(size[1], size[0], 3), dtype=np.uint8)
    frame = Image.fromarray(bg, mode="RGB")
    frame.paste(icon, at)
    return frame


def simple_offset() -> tuple[int, int, int, int]:
    """Digits box 60px wide immediately left of the icon."""
    return (-64, 0, 60, ICON_H)


def test_finds_the_icon_wherever_it_is() -> None:
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.7)

    for position in [(100, 100), (400, 250), (700, 40), (64, 0)]:
        match = locator.locate(make_frame(icon, position))
        assert match is not None, f"missed the icon at {position}"
        assert match.icon_box[:2] == position
        assert match.confidence > 0.9


def test_digits_box_tracks_the_icon() -> None:
    """The whole redesign: the crop must follow the marker, not stay put."""
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.7)

    a = locator.locate(make_frame(icon, (300, 200)))
    b = locator.locate(make_frame(icon, (500, 260)))
    assert a is not None and b is not None
    assert b.digits_box[0] - a.digits_box[0] == 200
    assert b.digits_box[1] - a.digits_box[1] == 60


def test_returns_none_when_the_marker_is_absent() -> None:
    """Camera turned away, or no active route."""
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.9)
    rng = np.random.default_rng(seed=3)
    empty = Image.fromarray(
        rng.integers(0, 60, size=(400, 800, 3), dtype=np.uint8), mode="RGB"
    )
    assert locator.locate(empty) is None


def test_digits_box_is_clamped_to_the_frame() -> None:
    """A marker near the left edge must still yield a valid, in-bounds crop."""
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.7)
    frame = make_frame(icon, (10, 100))
    match = locator.locate(frame)
    assert match is not None

    left, top, width, height = match.digits_box
    assert left >= 0 and top >= 0
    assert left + width <= frame.width
    assert top + height <= frame.height

    crop = locator.crop_digits(frame, match)
    assert crop.size == (width, height)


def test_crop_lands_on_the_digits() -> None:
    """Paste a bright bar where digits would be and confirm the crop covers it."""
    icon = make_icon()
    frame = make_frame(icon, (400, 200))
    bar = Image.fromarray(np.full((ICON_H, 60, 3), 240, dtype=np.uint8), mode="RGB")
    frame.paste(bar, (400 - 64, 200))

    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.7)
    match = locator.locate(frame)
    assert match is not None
    crop = np.asarray(locator.crop_digits(frame, match).convert("L"))
    assert crop.mean() > 200  # the crop is essentially all bar


def test_scaling_adjusts_template_and_offset() -> None:
    """A different resolution scales both the template and the digits offset."""
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.6, scale=2.0)
    assert locator.template_size == (ICON_W * 2, ICON_H * 2)

    big_icon = icon.resize((ICON_W * 2, ICON_H * 2), Image.LANCZOS)
    match = locator.locate(make_frame(big_icon, (300, 150), size=(1600, 800)))
    assert match is not None
    # Offset doubled too: -64 * 2 = -128 from the icon's left edge.
    assert match.digits_box[0] == 300 - 128
    assert match.digits_box[2] == 120


def test_tiny_template_is_rejected() -> None:
    with pytest.raises(LocatorError):
        MarkerLocator(Image.new("RGB", (2, 2)), simple_offset())


def test_frame_smaller_than_template_is_an_error() -> None:
    locator = MarkerLocator(make_icon(), simple_offset())
    with pytest.raises(LocatorError):
        locator.locate(Image.new("RGB", (8, 8)))


# -- offset derivation ---------------------------------------------------


def test_offset_is_relative_to_the_icon() -> None:
    digits = (100, 50, 40, 18)   # left, top, w, h
    icon = (150, 48, 16, 16)
    dx, dy, dw, dh = digits_offset_from_boxes(digits, icon, left_slack=0.0)
    assert dx == 100 - 150       # digits start 50px left of the icon
    # Width now runs from there to just short of the icon, not merely the
    # calibrated 40px, so longer numbers are not clipped.
    assert dx + dw == -ICON_CLEARANCE_PX
    assert dw >= 40
    assert dh > 18               # vertical padding was added
    assert dy < 50 - 48


def test_left_slack_widens_the_box_leftward() -> None:
    """Calibrating on a short number must still capture a longer one."""
    digits = (100, 50, 40, 18)
    icon = (150, 48, 16, 16)
    dx, _dy, dw, _dh = digits_offset_from_boxes(digits, icon, left_slack=2.0)

    assert dx == (100 - 80) - 150              # grew to the left by 2x40
    assert dw >= 40 + 80                       # at least the calibrated span


def test_marker_at_the_edge_is_reported_as_seen_without_digits() -> None:
    """Distinct from not finding the marker at all.

    The icon pinned to the left edge puts the digits off-screen. That must read
    as "seen, unreadable" rather than "camera pointed away", because the two
    call for different explanations in the log.
    """
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.7)
    match = locator.locate(make_frame(icon, (0, 0)))

    assert match is not None
    assert match.confidence > 0.9
    assert not match.has_digits


def test_normal_placement_has_digits() -> None:
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.7)
    match = locator.locate(make_frame(icon, (300, 150)))
    assert match is not None and match.has_digits


def test_best_confidence_separates_present_from_absent() -> None:
    """Underpins the threshold advice given during calibration.

    Measured on a real 3440x1440 game frame: the marker scores 1.00 while
    ordinary scenery tops out near 0.72. A threshold must sit between them,
    which is why the default is 0.85 rather than 0.70.
    """
    icon = make_icon()
    locator = MarkerLocator(icon, simple_offset(), match_threshold=0.85)

    present = locator.best_confidence(make_frame(icon, (300, 150)))
    rng = np.random.default_rng(seed=11)
    absent = locator.best_confidence(
        Image.fromarray(rng.integers(0, 60, size=(400, 800, 3), dtype=np.uint8), mode="RGB")
    )

    assert present > 0.95
    assert absent < present
    # The default threshold must fall in the gap.
    assert absent < 0.85 <= present


def test_box_reaches_to_just_short_of_the_icon() -> None:
    """Regression: a live 14000 was clipped to 1400 - a 10x error.

    Calibration on "600" showed a 17px gap to the icon, but a five-digit
    reading sat ~8px away. Preserving the calibrated gap cut the last digit
    off, so the box must hug the icon instead.
    """
    digits = (100, 50, 40, 18)   # ends at 139
    icon = (157, 48, 16, 16)     # 17px gap, as measured at calibration
    dx, _dy, dw, _dh = digits_offset_from_boxes(digits, icon, left_slack=2.0)

    right_rel = dx + dw
    assert right_rel == -ICON_CLEARANCE_PX, "right edge must sit against the icon"
    # It must extend well past where the calibrated digits ended.
    calibrated_right_rel = (100 + 40) - 157
    assert right_rel > calibrated_right_rel


def test_a_longer_number_is_fully_covered() -> None:
    """Five digits at the calibrated pitch must fit inside the derived box."""
    digits = (1633, 1183, 23, 10)          # "600": 3 digits, ~7.7px each
    icon = (1673, 1181, 17, 16)
    dx, _dy, dw, _dh = digits_offset_from_boxes(digits, icon, left_slack=2.0)

    # Place a five-digit number ending 8px before the icon, as observed live.
    icon_left = 1766
    pitch = 23 / 3
    number_right = icon_left - 8
    number_left = number_right - round(pitch * 5)

    box_left, box_right = icon_left + dx, icon_left + dx + dw
    assert box_left <= number_left, "clipped on the left"
    assert box_right >= number_right, "clipped on the right"
