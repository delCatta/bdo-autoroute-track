"""Heartbeats fire on the clock AND on real progress.

A one-minute heartbeat would otherwise repeat the same number while the route
crawls, or while a boat sits still, burying the alerts that matter.
"""

from __future__ import annotations

from pathlib import Path

from bdo_autoroute.alerts import Alert
from bdo_autoroute.marker import Offset
from bdo_autoroute.monitor import Monitor, Timer
from bdo_autoroute.settings import Calibration, Settings
from bdo_autoroute.voyage import State, Status


class Outbox:
    """Stands in for Discord."""

    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def deliver(self, alert: Alert) -> bool:
        self.sent.append(alert)
        return True


def monitor(tmp_path: Path, **overrides) -> tuple[Monitor, Outbox]:
    fields = {
        "heartbeat_minutes": 1,
        "heartbeat_min_progress_m": 150.0,
        "samples_enabled": False,
    }
    fields.update(overrides)
    settings = Settings(**fields)
    calibration = Calibration(Offset(-86, 0, 83, 14), 3440, 1440, "icon_template.png")
    outbox = Outbox()
    return (
        Monitor(
            settings,
            calibration,
            readout=None,
            discord=outbox,
            voyage=None,
            samples_dir=tmp_path,
        ),
        outbox,
    )


def travelling(distance: float) -> Status:
    return Status(
        state=State.TRAVELLING,
        distance_m=distance,
        eta_seconds=600.0,
        stalled_seconds=0.0,
        event=None,
    )


class TestWorthAHeartbeat:
    def test_the_first_heartbeat_always_goes_out(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        assert watcher._worth_a_heartbeat(travelling(5000), now=0.0)

    def test_a_heartbeat_waits_for_the_interval(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        watcher._worth_a_heartbeat(travelling(5000), now=0.0)
        assert not watcher._worth_a_heartbeat(travelling(4000), now=30.0)

    def test_a_heartbeat_waits_for_real_progress(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        watcher._worth_a_heartbeat(travelling(5000), now=0.0)
        assert not watcher._worth_a_heartbeat(travelling(4900), now=120.0)

    def test_a_heartbeat_goes_out_once_both_are_satisfied(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        watcher._worth_a_heartbeat(travelling(5000), now=0.0)
        assert watcher._worth_a_heartbeat(travelling(4800), now=120.0)

    def test_progress_is_measured_from_the_last_heartbeat_not_the_last_poll(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        watcher._worth_a_heartbeat(travelling(5000), now=0.0)

        for moment, distance in ((60.0, 4950), (120.0, 4900), (180.0, 4880)):
            assert not watcher._worth_a_heartbeat(travelling(distance), now=moment)

        assert watcher._worth_a_heartbeat(travelling(4840), now=240.0)

    def test_a_stationary_route_never_heartbeats_again(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        watcher._worth_a_heartbeat(travelling(2000), now=0.0)
        for minute in range(1, 20):
            assert not watcher._worth_a_heartbeat(travelling(2000), now=minute * 60.0)

    def test_a_reading_without_a_distance_never_heartbeats(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        assert not watcher._worth_a_heartbeat(travelling(None), now=0.0)

    def test_heartbeats_off_means_never(self, tmp_path):
        watcher, _ = monitor(tmp_path, heartbeat_minutes=0)
        assert not watcher._worth_a_heartbeat(travelling(5000), now=0.0)


class TestTimer:
    """Regression: last_at of 0.0 must not read as "never fired"."""

    def test_due_is_true_before_the_first_mark(self):
        assert Timer(interval=60).due(now=0.0)

    def test_due_is_false_immediately_after_a_mark_at_time_zero(self):
        timer = Timer(interval=60)
        timer.mark(0.0)
        assert not timer.due(now=30.0)

    def test_due_returns_once_the_interval_has_passed(self):
        timer = Timer(interval=60)
        timer.mark(0.0)
        assert timer.due(now=60.0)

    def test_an_interval_of_zero_is_never_due(self):
        assert not Timer(interval=0).due(now=1000.0)


class TestFirstHeartbeatWording:
    """The first heartbeat must not claim motion it has not seen.

    Live at 10:32:44 it said "Still under way" about a route that had been
    motionless for 31s. It fires before any progress can be measured, so it
    reports that it is watching instead.
    """

    def test_the_first_heartbeat_says_it_is_watching(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        assert watcher._heartbeat_for(travelling(4810)).headline == "Now watching"

    def test_later_heartbeats_report_progress(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        watcher._heartbeat_for(travelling(4810))
        assert watcher._heartbeat_for(travelling(4600)).headline == "Still under way"

    def test_neither_is_urgent(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        assert not watcher._heartbeat_for(travelling(4810)).urgent
        assert not watcher._heartbeat_for(travelling(4600)).urgent

    def test_the_greeting_still_reports_the_distance(self, tmp_path):
        watcher, _ = monitor(tmp_path)
        assert "4810m" in watcher._heartbeat_for(travelling(4810)).body
