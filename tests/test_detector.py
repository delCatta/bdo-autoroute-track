"""Tests for the voyage state machine.

Time is passed in explicitly, so a whole voyage can be replayed instantly.
"""

from __future__ import annotations

import pytest

from bdo_tracker.detector import State, VoyageDetector, format_duration


def make_detector(**overrides: float) -> VoyageDetector:
    kwargs: dict[str, float] = {
        "arrival_threshold_m": 60.0,
        "movement_epsilon_m": 15.0,
        "stuck_after_seconds": 180,
        "missing_confirm_polls": 3,
        "near_arrival_m": 400.0,
    }
    kwargs.update(overrides)
    return VoyageDetector(**kwargs)  # type: ignore[arg-type]


def test_falling_distance_reads_as_sailing() -> None:
    det = make_detector()
    det.update(3970, now=0)
    status = det.update(3500, now=30)
    assert status.state is State.SAILING
    assert status.distance_m == 3500


def test_reaching_the_threshold_reports_arrival() -> None:
    """Arrival needs two consecutive sub-threshold readings; see
    tests/test_misread_guards.py for why one is not enough."""
    det = make_detector()
    det.update(3970, now=0)
    det.update(500, now=30)
    assert det.update(40, now=60).state is State.SAILING   # unconfirmed
    status = det.update(38, now=90)
    assert status.state is State.ARRIVED
    assert status.event is not None
    assert status.event.previous is State.SAILING


def test_no_progress_for_long_enough_reports_stuck() -> None:
    det = make_detector(stuck_after_seconds=180)
    det.update(2000, now=0)
    # Small wobbles inside the epsilon must not count as progress.
    for t in (30, 60, 90, 120, 150):
        assert det.update(1995, now=t).state is State.SAILING
    status = det.update(1997, now=181)
    assert status.state is State.STUCK
    assert status.event is not None


def test_jitter_alone_does_not_trigger_stuck() -> None:
    """Readings that genuinely fall must keep resetting the stall timer."""
    det = make_detector(stuck_after_seconds=180)
    distance = 5000.0
    for step in range(20):
        distance -= 100
        status = det.update(distance, now=step * 30)
    assert status.state is State.SAILING


def test_stuck_boat_recovers_to_sailing() -> None:
    det = make_detector(stuck_after_seconds=120)
    det.update(2000, now=0)
    det.update(2000, now=130)
    assert det.state is State.STUCK
    status = det.update(1800, now=160)
    assert status.state is State.SAILING
    assert status.event is not None
    assert status.event.previous is State.STUCK


def test_readout_vanishing_near_the_destination_means_arrived() -> None:
    det = make_detector(missing_confirm_polls=3, near_arrival_m=400.0)
    det.update(300, now=0)
    assert det.update(None, now=30).state is State.SAILING  # not yet confirmed
    assert det.update(None, now=60).state is State.SAILING
    status = det.update(None, now=90)
    assert status.state is State.ARRIVED


def test_readout_vanishing_far_out_means_signal_lost() -> None:
    det = make_detector(missing_confirm_polls=3, near_arrival_m=400.0)
    det.update(5000, now=0)
    for t in (30, 60):
        det.update(None, now=t)
    status = det.update(None, now=90)
    assert status.state is State.SIGNAL_LOST


def test_a_single_missed_read_does_not_change_state() -> None:
    det = make_detector(missing_confirm_polls=3)
    det.update(3000, now=0)
    det.update(2500, now=30)
    status = det.update(None, now=60)
    assert status.state is State.SAILING
    assert status.event is None


def test_missing_counter_resets_after_a_good_read() -> None:
    det = make_detector(missing_confirm_polls=3)
    det.update(5000, now=0)
    det.update(None, now=30)
    det.update(None, now=60)
    det.update(4800, now=90)  # recovered
    status = det.update(None, now=120)
    assert status.state is State.SAILING


def test_a_new_route_restarts_progress_tracking() -> None:
    """Arriving then setting a fresh, longer route must not read as stuck."""
    det = make_detector(stuck_after_seconds=180)
    det.update(200, now=0)
    det.update(30, now=30)
    det.update(28, now=60)   # second sub-threshold reading confirms arrival
    assert det.state is State.ARRIVED

    status = det.update(6000, now=90)  # new auto-route set
    assert status.state is State.SAILING
    # The old stall timer must not carry over.
    assert det.update(5900, now=120).state is State.SAILING


def test_eta_is_derived_from_the_closing_rate() -> None:
    det = make_detector()
    det.update(1000, now=0)
    status = det.update(900, now=100)  # 1 m/s, 900 m left
    assert status.eta_seconds == pytest.approx(900, rel=0.05)


def test_eta_is_absent_when_not_moving() -> None:
    det = make_detector()
    det.update(1000, now=0)
    status = det.update(1000, now=30)
    assert status.eta_seconds is None


def test_events_fire_only_on_transitions() -> None:
    det = make_detector()
    first = det.update(3000, now=0)
    assert first.event is not None  # STARTING -> SAILING
    assert det.update(2900, now=30).event is None
    assert det.update(2800, now=60).event is None


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0s"), (45, "45s"), (90, "1m 30s"), (3600, "1h 0m"), (5400, "1h 30m"), (None, "unknown")],
)
def test_format_duration(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_a_route_change_does_not_poison_the_eta() -> None:
    """Live regression: 10710m -> 657m on a new route reported "eta=0s".

    Averaging across a jump gives a speed no ship could sail. The rate history
    restarts instead, so the ETA reflects the new journey only.
    """
    det = make_detector()
    det.update(10820, now=0)
    det.update(10710, now=6)
    status = det.update(657, now=13)      # user picked a nearer destination
    assert status.eta_seconds is None     # nothing sensible to say yet

    det.update(590, now=43)
    status = det.update(530, now=73)      # ~2 m/s on the new route
    assert status.eta_seconds is not None
    assert status.eta_seconds == pytest.approx(530 / 2.0, rel=0.3)


def test_an_impossible_closing_speed_yields_no_eta() -> None:
    det = make_detector()
    det.update(5000, now=0)
    status = det.update(100, now=1)       # 4900 m/s
    assert status.eta_seconds is None


def test_normal_sailing_speeds_still_produce_an_eta() -> None:
    """Real readings cruise near 20 m/s, comfortably under the cap."""
    det = make_detector()
    det.update(12410, now=0)
    status = det.update(12240, now=8)     # ~21 m/s, as observed live
    assert status.eta_seconds is not None
