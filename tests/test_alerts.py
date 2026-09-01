"""Alert: what gets said, and how loudly."""

from __future__ import annotations

from PIL import Image

from bdo_autoroute.alerts import Alert
from bdo_autoroute.voyage import Event, State, Status

URGENT = ["ARRIVED", "STUCK", "SIGNAL_LOST"]


def event(state=State.ARRIVED, previous=State.TRAVELLING, **overrides) -> Event:
    fields = {
        "state": state,
        "previous": previous,
        "message": "Arrived, 41m remaining.",
        "distance_m": 41.0,
        "eta_seconds": None,
        "pending_arrival": False,
    }
    fields.update(overrides)
    return Event(**fields)


def status(state=State.STUCK, **overrides) -> Status:
    fields = {
        "state": state,
        "distance_m": 2140.0,
        "eta_seconds": None,
        "stalled_seconds": 180.0,
        "event": None,
        "pending_arrival": False,
    }
    fields.update(overrides)
    return Status(**fields)


class TestForEvent:
    def test_for_event_takes_its_headline_from_the_state(self):
        assert Alert.for_event(event(), urgent_states=URGENT).headline == "Arrived"

    def test_for_event_says_possibly_arrived_while_confirming(self):
        pending = event(state=State.TRAVELLING, pending_arrival=True)
        assert Alert.for_event(pending, urgent_states=URGENT).headline == "Possibly arrived"

    def test_for_event_is_urgent_only_for_the_configured_states(self):
        assert Alert.for_event(event(State.ARRIVED), urgent_states=URGENT).urgent
        assert not Alert.for_event(
            event(State.TRAVELLING, previous=State.STARTING), urgent_states=URGENT
        ).urgent

    def test_for_event_records_the_state_it_came_from(self):
        alert = Alert.for_event(event(), urgent_states=URGENT)
        assert alert.details["Was"] == "TRAVELLING"

    def test_for_event_includes_an_eta_when_there_is_one(self):
        alert = Alert.for_event(event(eta_seconds=90), urgent_states=URGENT)
        assert alert.details["ETA"] == "1m 30s"

    def test_for_event_merges_extra_details(self):
        alert = Alert.for_event(
            event(State.SIGNAL_LOST), urgent_states=URGENT, details={"Game minimised": "yes"}
        )
        assert alert.details["Game minimised"] == "yes"


class TestStillStuck:
    def test_still_stuck_is_always_urgent(self):
        assert Alert.still_stuck(status()).urgent

    def test_still_stuck_reports_how_long_and_how_far(self):
        body = Alert.still_stuck(status()).body
        assert "3m 0s" in body
        assert "2140m" in body

    def test_still_stuck_copes_without_a_distance(self):
        assert "unknown" in Alert.still_stuck(status(distance_m=None)).body.lower()


class TestHeartbeat:
    def test_heartbeat_is_never_urgent(self):
        assert not Alert.heartbeat(status(State.TRAVELLING)).urgent

    def test_heartbeat_reports_the_distance_remaining(self):
        assert "2140m" in Alert.heartbeat(status(State.TRAVELLING)).body


class TestColour:
    def test_colour_differs_between_good_and_bad_news(self):
        arrived = Alert.for_event(event(State.ARRIVED), urgent_states=URGENT)
        stuck = Alert.still_stuck(status(State.STUCK))
        assert arrived.colour != stuck.colour


class TestShowing:
    def test_showing_attaches_a_frame(self):
        frame = Image.new("RGB", (10, 10))
        assert Alert.heartbeat(status(State.TRAVELLING)).showing(frame).screenshot is frame

    def test_showing_nothing_leaves_the_alert_alone(self):
        alert = Alert.heartbeat(status(State.TRAVELLING))
        assert alert.showing(None) is alert


class TestStampedDetails:
    def test_stamped_details_adds_the_time(self):
        assert "Time" in Alert.heartbeat(status(State.TRAVELLING)).stamped_details
