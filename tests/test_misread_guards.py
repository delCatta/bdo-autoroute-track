"""Guards against OCR misreads, both taken from observed live failures.

A live frame showing 1169m came back from OCR as "11'69 9". Two separate
defects were needed to turn that into a reported 9m:

  1. the apostrophe split "1169" into "11" and "69"
  2. a right-most preference then picked the stray "9"

And one more would have made it dangerous: a single sub-threshold reading was
enough to declare arrival, so a bogus 9 would have told the user their boat had
docked when it was still over a kilometre out.
"""

from __future__ import annotations

import pytest

from bdo_tracker.detector import State, VoyageDetector
from bdo_tracker.ocr import parse_distance

MIN_M, MAX_M = 0.0, 20000.0


def parse(text: str) -> float | None:
    return parse_distance(text, MIN_M, MAX_M)


def test_the_exact_observed_misread() -> None:
    """The literal string a live frame produced for a true reading of 1169m."""
    assert parse("11'69 9") == 1169.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("11'69", 1169.0),
        ("3`970", 3970.0),
        ("3’970", 3970.0),
        ("1´234", 1234.0),
        ("1,169", 1169.0),
    ],
)
def test_separators_are_joined_not_split(text: str, expected: float) -> None:
    assert parse(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("11'69 9", 1169.0),   # stray digit to the right
        ("9 1169", 1169.0),    # stray digit to the left
        ("27 3970", 3970.0),   # unrelated UI text pulled in by the slack
        ("3970", 3970.0),
        ("600", 600.0),
    ],
)
def test_longest_run_wins_over_stray_fragments(text: str, expected: float) -> None:
    assert parse(text) == expected


def test_ties_break_toward_the_icon() -> None:
    """Equal digit counts: take the right-most, nearest the icon."""
    assert parse("111 222") == 222.0


def test_km_decimals_still_work() -> None:
    assert parse("1.2km") == 1200.0


# -- arrival confirmation ------------------------------------------------


def make_detector(**overrides):
    kwargs = {
        "arrival_threshold_m": 70.0,
        "movement_epsilon_m": 15.0,
        "stuck_after_seconds": 180,
        "missing_confirm_polls": 4,
        "near_arrival_m": 400.0,
        "arrival_confirm_polls": 2,
    }
    kwargs.update(overrides)
    return VoyageDetector(**kwargs)


def test_one_wild_reading_does_not_declare_arrival() -> None:
    """The failure this guard exists for: 1169m misread as 9m."""
    det = make_detector()
    det.update(3000, now=0)
    det.update(1264, now=30)
    status = det.update(9, now=60)          # the misread
    assert status.state is State.SAILING
    assert status.event is None

    status = det.update(1169, now=90)       # reality reasserts itself
    assert status.state is State.SAILING


def test_two_consecutive_readings_do_declare_arrival() -> None:
    det = make_detector()
    det.update(3000, now=0)
    det.update(500, now=30)
    assert det.update(41, now=60).state is State.SAILING   # first, unconfirmed
    status = det.update(38, now=90)                        # confirmed
    assert status.state is State.ARRIVED
    assert status.event is not None


def test_red_indicator_confirms_arrival_immediately() -> None:
    """When the game itself says you are close, one reading is enough."""
    det = make_detector()
    det.update(3000, now=0)
    status = det.update(41, now=30, near_indicator=True)
    assert status.state is State.ARRIVED


def test_the_streak_resets_when_the_boat_is_far_again() -> None:
    det = make_detector()
    det.update(3000, now=0)
    det.update(9, now=30)      # misread, streak = 1
    det.update(1169, now=60)   # real, streak reset
    assert det.update(50, now=90).state is State.SAILING   # must confirm again
    assert det.update(45, now=120).state is State.ARRIVED


def test_confirm_of_one_restores_immediate_arrival() -> None:
    det = make_detector(arrival_confirm_polls=1)
    det.update(3000, now=0)
    assert det.update(41, now=30).state is State.ARRIVED


def test_pending_arrival_is_flagged_for_the_alert_title() -> None:
    """A live alert once read "Under way" over a "Possible arrival" body.

    The flag lets the notifier title match what the message actually says.
    """
    det = make_detector()
    status = det.update(10, now=0)          # first sub-threshold reading
    assert status.state is State.SAILING
    assert status.pending_arrival
    assert status.event is not None and status.event.pending_arrival

    status = det.update(8, now=30)          # confirmed
    assert status.state is State.ARRIVED
    assert not status.pending_arrival
    assert status.event is not None and not status.event.pending_arrival


def test_pending_arrival_clears_when_the_boat_is_far_again() -> None:
    det = make_detector()
    det.update(3000, now=0)
    assert det.update(9, now=30).pending_arrival        # misread
    assert not det.update(1169, now=60).pending_arrival # reality


def test_clipped_digit_scenario_is_covered_by_the_locator_tests() -> None:
    """Marker: the 14000 -> 1400 clipping regression lives in test_locator.py.

    Kept here as a pointer, because the three live misreads (11'69 9, the
    clipped 14000, and the poisoned ETA) are easy to confuse with each other.
    """
    assert parse("14000") == 14000.0
    assert parse("1400") == 1400.0
