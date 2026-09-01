"""Early warnings: hear about arrivals and stalls while you can still act.

`approaching` and `stalling` are one-shot notices that fire before the confirmed
ARRIVED and STUCK states. They ride alongside the state rather than replacing
it, so the confirmation guards that stop a single misread declaring arrival
still apply to the state itself.
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
        "approaching_m": 500.0,
        "stalling_after_seconds": 60,
    }
    settings.update(overrides)
    return Voyage(**settings)


class TestApproaching:
    def test_approaching_fires_when_the_distance_first_drops_below_the_range(self):
        trip = voyage()
        assert not trip.update(900, now=0).approaching
        assert trip.update(480, now=30).approaching

    def test_approaching_fires_only_once_per_route(self):
        trip = voyage()
        trip.update(900, now=0)
        assert trip.update(480, now=30).approaching
        assert not trip.update(400, now=60).approaching
        assert not trip.update(300, now=90).approaching

    def test_approaching_fires_when_the_readout_turns_red_while_still_far(self):
        trip = voyage()
        trip.update(1400, now=0)
        assert trip.update(900, now=30, near_indicator=True).approaching

    def test_approaching_fires_again_on_a_new_route(self):
        trip = voyage()
        trip.update(900, now=0)
        assert trip.update(480, now=30).approaching

        trip.update(6000, now=60)
        trip.update(5980, now=90)
        assert not trip.update(3000, now=240).approaching
        assert trip.update(450, now=390).approaching

    def test_approaching_is_never_set_without_a_reading(self):
        trip = voyage()
        trip.update(480, now=0)
        assert not trip.update(None, now=30).approaching

    def test_approaching_arrives_before_the_arrived_state(self):
        trip = voyage()
        trip.update(900, now=0)
        warned = trip.update(480, now=30)
        assert warned.approaching
        assert warned.state is State.TRAVELLING


class TestStalling:
    def test_stalling_fires_well_before_the_stuck_state(self):
        trip = voyage(stalling_after_seconds=60, stuck_after_seconds=180)
        trip.update(2000, now=0)
        assert not trip.update(1995, now=30).stalling

        warned = trip.update(1995, now=61)
        assert warned.stalling
        assert warned.state is State.TRAVELLING

    def test_stalling_fires_only_once_per_route(self):
        trip = voyage(stalling_after_seconds=60)
        trip.update(2000, now=0)
        assert trip.update(1995, now=61).stalling
        assert not trip.update(1995, now=90).stalling

    def test_stalling_resets_after_real_progress(self):
        trip = voyage(stalling_after_seconds=60)
        trip.update(2000, now=0)
        assert trip.update(1995, now=61).stalling

        trip.update(1500, now=90)
        assert not trip.update(1495, now=120).stalling

    def test_stalling_fires_again_on_a_new_route(self):
        trip = voyage(stalling_after_seconds=60)
        trip.update(2000, now=0)
        assert trip.update(1995, now=61).stalling

        trip.update(9000, now=90)
        trip.update(8990, now=120)
        assert trip.update(8985, now=200).stalling

    def test_stalling_is_never_set_without_a_reading(self):
        trip = voyage(stalling_after_seconds=60)
        trip.update(2000, now=0)
        assert not trip.update(None, now=90).stalling


class TestNoticesAndStates:
    def test_a_notice_does_not_replace_the_state_change(self):
        trip = voyage()
        trip.update(900, now=0)
        status = trip.update(480, now=30)
        assert status.approaching
        assert status.state is State.TRAVELLING

    def test_arrival_still_needs_confirming_after_an_approach_warning(self):
        trip = voyage()
        trip.update(900, now=0)
        trip.update(480, now=30)
        trip.update(200, now=60)
        assert trip.update(40, now=90).state is State.TRAVELLING
        assert trip.update(38, now=120).state is State.ARRIVED
