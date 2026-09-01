"""Voyage: distance readings in, state out."""

from __future__ import annotations

import pytest

from bdo_autoroute.voyage import State, Voyage, duration


def voyage(**overrides) -> Voyage:
    settings = {
        "arrival_threshold_m": 70.0,
        "movement_epsilon_m": 15.0,
        "stuck_after_seconds": 180,
        "missing_confirm_polls": 4,
        "near_arrival_m": 400.0,
        "arrival_confirm_polls": 2,
    }
    settings.update(overrides)
    return Voyage(**settings)


class TestState:
    def test_headline_names_the_state(self):
        assert State.ARRIVED.headline == "Arrived"
        assert State.STUCK.headline == "Looks stuck"

    def test_trouble_is_true_for_states_needing_a_human(self):
        assert State.STUCK.trouble
        assert State.SIGNAL_LOST.trouble

    def test_trouble_is_false_while_things_go_well(self):
        assert not State.TRAVELLING.trouble
        assert not State.ARRIVED.trouble


class TestUpdate:
    def test_update_returns_travelling_while_the_distance_falls(self):
        trip = voyage()
        trip.update(3970, now=0)
        status = trip.update(3500, now=30)
        assert status.travelling
        assert status.distance_m == 3500

    def test_update_returns_arrived_after_two_readings_below_the_threshold(self):
        trip = voyage()
        trip.update(500, now=0)
        trip.update(300, now=30)
        trip.update(100, now=60)
        assert trip.update(40, now=90).travelling
        assert trip.update(38, now=120).state is State.ARRIVED

    def test_update_returns_stuck_after_too_long_without_progress(self):
        trip = voyage(stuck_after_seconds=180)
        trip.update(2000, now=0)
        for moment in (30, 60, 90, 120, 150):
            assert trip.update(1995, now=moment).travelling
        assert trip.update(1997, now=181).stuck

    def test_update_returns_travelling_again_once_a_stuck_boat_moves(self):
        trip = voyage(stuck_after_seconds=120)
        trip.update(2000, now=0)
        trip.update(2000, now=130)
        assert trip.state is State.STUCK

        status = trip.update(1800, now=160)
        assert status.travelling
        assert status.event.previous is State.STUCK

    def test_update_ignores_jitter_smaller_than_the_epsilon(self):
        trip = voyage(stuck_after_seconds=180)
        distance = 5000.0
        for step in range(20):
            distance -= 100
            status = trip.update(distance, now=step * 30)
        assert status.travelling

    def test_update_starts_over_when_a_longer_route_is_set(self):
        trip = voyage(stuck_after_seconds=180)
        trip.update(200, now=0)
        trip.update(30, now=30)
        trip.update(28, now=60)
        assert trip.state is State.ARRIVED

        trip.update(6000, now=90)
        assert trip.update(5980, now=120).travelling
        assert trip.update(5900, now=150).travelling


class TestMissingReadings:
    def test_update_holds_state_through_a_single_missed_reading(self):
        trip = voyage()
        trip.update(3000, now=0)
        trip.update(2500, now=30)
        status = trip.update(None, now=60)
        assert status.travelling
        assert not status.changed

    def test_update_returns_arrived_when_the_marker_clears_close_to_the_end(self):
        trip = voyage(missing_confirm_polls=3, near_arrival_m=400.0)
        trip.update(300, now=0)
        for moment in (30, 60):
            assert trip.update(None, now=moment).travelling
        assert trip.update(None, now=90).state is State.ARRIVED

    def test_update_returns_signal_lost_when_the_marker_clears_far_out(self):
        trip = voyage(missing_confirm_polls=3)
        trip.update(5000, now=0)
        for moment in (30, 60):
            trip.update(None, now=moment)
        assert trip.update(None, now=90).state is State.SIGNAL_LOST

    def test_update_forgets_missed_readings_after_a_good_one(self):
        trip = voyage(missing_confirm_polls=3)
        trip.update(5000, now=0)
        trip.update(None, now=30)
        trip.update(None, now=60)
        trip.update(4800, now=90)
        assert trip.update(None, now=120).travelling


class TestEta:
    def test_eta_seconds_follows_the_closing_rate(self):
        trip = voyage()
        trip.update(1000, now=0)
        assert trip.update(900, now=100).eta_seconds == pytest.approx(900, rel=0.05)

    def test_eta_seconds_is_none_while_stationary(self):
        trip = voyage()
        trip.update(1000, now=0)
        assert trip.update(1000, now=30).eta_seconds is None

    def test_eta_seconds_is_none_across_a_route_change(self):
        trip = voyage()
        trip.update(10820, now=0)
        trip.update(10710, now=6)
        trip.update(657, now=13)
        assert trip.update(650, now=20).eta_seconds is None

    def test_eta_seconds_recovers_on_the_new_route(self):
        trip = voyage()
        trip.update(10820, now=0)
        trip.update(657, now=13)
        trip.update(650, now=43)
        trip.update(590, now=73)
        status = trip.update(530, now=103)
        assert status.eta_seconds == pytest.approx(530 / 2.0, rel=0.4)

    def test_eta_seconds_is_none_for_impossible_speeds(self):
        trip = voyage()
        trip.update(5000, now=0)
        assert trip.update(100, now=1).eta_seconds is None

    def test_eta_seconds_survives_ordinary_sailing_speeds(self):
        trip = voyage()
        trip.update(12410, now=0)
        assert trip.update(12240, now=8).eta_seconds is not None


class TestEvents:
    def test_event_appears_only_when_the_state_changes(self):
        trip = voyage()
        assert trip.update(3000, now=0).changed
        assert not trip.update(2900, now=30).changed
        assert not trip.update(2800, now=60).changed


class TestDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0, "0s"), (45, "45s"), (90, "1m 30s"), (3600, "1h 0m"), (None, "unknown")],
    )
    def test_duration_reads_as_english(self, seconds, expected):
        assert duration(seconds) == expected
