"""A flickering misread must not move the baseline.

Seen live with a deliberately stalled route at 1480m: OCR kept dropping the
leading digit, so readings alternated 1480 / 480 / 1480. Every flip looked like
a kilometre of progress and reset the stall timer, so STUCK could never fire and
the route would have been watched forever.

A jump no route could travel is now held until a second reading agrees with it.
Real route changes confirm on the next poll; a flicker never does.
"""

from __future__ import annotations

from bdo_autoroute.voyage import State, Voyage


def voyage(**overrides) -> Voyage:
    settings = {
        "arrival_threshold_m": 70.0,
        "movement_epsilon_m": 15.0,
        "stuck_after_seconds": 180,
        "missing_confirm_polls": 4,
        "near_arrival_m": 400.0,
        "arrival_confirm_polls": 2,
        "stalling_after_seconds": 60,
    }
    settings.update(overrides)
    return Voyage(**settings)


class TestFlicker:
    def test_a_dropped_leading_digit_does_not_reset_the_stall_timer(self):
        trip = voyage()
        trip.update(1480, now=0)

        status = None
        for step, moment in enumerate(range(30, 210, 30)):
            reading = 480 if step % 2 == 0 else 1480
            status = trip.update(reading, now=moment)

        assert status.stalled_seconds >= 180
        assert status.state is State.STUCK

    def test_the_baseline_stays_on_the_stable_reading(self):
        trip = voyage()
        trip.update(1480, now=0)
        assert trip.update(480, now=30).distance_m == 1480
        assert trip.update(1480, now=60).distance_m == 1480
        assert trip.update(480, now=90).distance_m == 1480

    def test_a_single_wild_reading_is_ignored(self):
        trip = voyage()
        trip.update(3000, now=0)
        trip.update(2900, now=30)
        assert trip.update(9, now=60).distance_m == 2900
        assert trip.update(2800, now=90).distance_m == 2800


class TestConfirmedRouteChange:
    def test_a_new_route_is_accepted_once_a_second_reading_agrees(self):
        trip = voyage()
        trip.update(1480, now=0)
        assert trip.update(9000, now=30).distance_m == 1480

        status = trip.update(8980, now=60)
        assert status.distance_m == 8980
        assert status.state is State.TRAVELLING

    def test_a_confirmed_route_change_clears_the_old_stall(self):
        trip = voyage(stuck_after_seconds=120)
        trip.update(2000, now=0)
        trip.update(2000, now=130)
        assert trip.state is State.STUCK

        trip.update(9000, now=160)
        status = trip.update(8980, now=190)
        assert status.state is State.TRAVELLING
        assert status.stalled_seconds < 120

    def test_ordinary_travel_is_never_held_back(self):
        trip = voyage()
        distance = 5000.0
        for step in range(10):
            distance -= 300
            status = trip.update(distance, now=step * 30)
        assert status.distance_m == distance
        assert status.state is State.TRAVELLING

    def test_fast_travel_within_reach_is_accepted(self):
        trip = voyage()
        trip.update(5000, now=0)
        assert trip.update(4400, now=30).distance_m == 4400

    def test_arrival_readings_are_never_treated_as_jumps(self):
        trip = voyage()
        trip.update(400, now=0)
        trip.update(200, now=30)
        assert trip.update(60, now=60).state is State.TRAVELLING
        assert trip.update(50, now=90).state is State.ARRIVED
