"""The game turns the distance readout red when you are close to the destination.

Two things follow from that, and both are tested here:

  1. Thresholding must not use luminance. Red text has a luminance around 105,
     so a threshold that keeps white text (232) would drop red text entirely --
     blinding the reader at the exact moment arrival matters most.
  2. The red state is a usable near-arrival signal in its own right, because the
     number does not always count down to zero before the readout disappears.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from bdo_tracker.detector import State, VoyageDetector
from bdo_tracker.ocr import (
    RED_RATIO_THRESHOLD,
    Reading,
    preprocess,
    red_ratio,
    value_channel,
)

WHITE_TEXT = (232, 230, 220)
RED_TEXT = (226, 62, 48)
BACKGROUND = (18, 20, 26)
THRESHOLD = 150


def swatch(colour: tuple[int, int, int], size=(40, 16)) -> Image.Image:
    """A block of glyph-coloured pixels on the HUD background."""
    arr = np.full((size[1], size[0], 3), BACKGROUND, dtype=np.uint8)
    arr[4:12, 6:34] = colour
    return Image.fromarray(arr, mode="RGB")


def test_red_text_would_be_lost_by_a_luminance_threshold() -> None:
    """Documents why value_channel exists rather than convert('L')."""
    red = Image.new("RGB", (4, 4), RED_TEXT)
    luminance = np.asarray(red.convert("L")).max()
    assert luminance < THRESHOLD, "premise: red is dim by luminance"
    assert value_channel(red).max() >= THRESHOLD, "value channel keeps it"


def test_white_and_red_both_survive_preprocessing() -> None:
    for colour in (WHITE_TEXT, RED_TEXT):
        prepared = preprocess(swatch(colour), upscale=2, brightness_threshold=THRESHOLD)
        arr = np.asarray(prepared)
        # Glyph pixels become black (0) on the white background.
        assert (arr == 0).any(), f"{colour} was dropped entirely"


def test_background_is_still_rejected() -> None:
    """Widening to the value channel must not let the dark HUD through."""
    flat = Image.new("RGB", (40, 16), BACKGROUND)
    prepared = preprocess(flat, upscale=1, brightness_threshold=THRESHOLD)
    assert np.asarray(prepared).min() == 255


def test_red_ratio_separates_the_two_states() -> None:
    assert red_ratio(swatch(WHITE_TEXT), THRESHOLD) < RED_RATIO_THRESHOLD
    assert red_ratio(swatch(RED_TEXT), THRESHOLD) >= RED_RATIO_THRESHOLD


def test_red_ratio_is_zero_when_nothing_is_bright() -> None:
    assert red_ratio(Image.new("RGB", (20, 10), BACKGROUND), THRESHOLD) == 0.0


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(0.0, False), (0.2, False), (RED_RATIO_THRESHOLD, True), (0.9, True)],
)
def test_near_indicator_flag(ratio: float, expected: bool) -> None:
    assert Reading(meters=90.0, raw_text="90", red_ratio=ratio).near_indicator is expected


# -- how the detector uses it -------------------------------------------


def make_detector() -> VoyageDetector:
    return VoyageDetector(
        arrival_threshold_m=70.0,
        movement_epsilon_m=15.0,
        stuck_after_seconds=180,
        missing_confirm_polls=3,
        near_arrival_m=400.0,
    )


def test_red_readout_rescues_arrival_when_the_number_stops_far_out() -> None:
    """The number does not always reach zero, and can vanish while still high.

    Without the red signal this sequence would be reported as SIGNAL_LOST.
    """
    det = make_detector()
    det.update(3000, now=0)
    det.update(900, now=30, near_indicator=True)  # game says: you are close
    for t in (60, 90):
        det.update(None, now=t)
    status = det.update(None, now=120)
    assert status.state is State.ARRIVED


def test_without_the_red_signal_a_vanishing_far_readout_is_still_a_loss() -> None:
    det = make_detector()
    det.update(3000, now=0)
    det.update(900, now=30)  # no red indicator
    for t in (60, 90):
        det.update(None, now=t)
    status = det.update(None, now=120)
    assert status.state is State.SIGNAL_LOST


def test_a_new_voyage_clears_the_remembered_red_signal() -> None:
    """Otherwise every later voyage would report arrival the moment it blinked."""
    det = make_detector()
    det.update(200, now=0, near_indicator=True)
    det.update(50, now=30)
    assert det.state is State.ARRIVED

    det.update(6000, now=60)  # fresh route
    for t in (90, 120):
        det.update(None, now=t)
    status = det.update(None, now=150)
    assert status.state is State.SIGNAL_LOST


def test_arrival_threshold_is_reached_before_zero() -> None:
    """70m counts as arrival, per how the readout actually behaves.

    Two readings, because a lone sub-threshold value can be a misread.
    """
    det = make_detector()
    det.update(500, now=0)
    assert det.update(69, now=30).state is State.SAILING
    assert det.update(66, now=60).state is State.ARRIVED
