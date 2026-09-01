"""Settings change while it runs, without restarting or losing the journey.

Rebuilding the Voyage on every settings change would silently restart the trip,
losing the stall timer at exactly the moment somebody is most likely to be
adjusting the stuck threshold.
"""

from __future__ import annotations

from pathlib import Path

from bdo_autoroute.marker import Offset
from bdo_autoroute.monitor import Monitor
from bdo_autoroute.outbox import Outbox
from bdo_autoroute.settings import Calibration, Settings
from bdo_autoroute.tray import Facts
from bdo_autoroute.voyage import State, Status, Voyage


class Channel:
    def __init__(self, name: str) -> None:
        self.name = name

    def deliver(self, alert) -> bool:
        return True


def voyage() -> Voyage:
    return Voyage(
        arrival_threshold_m=70.0,
        movement_epsilon_m=15.0,
        stuck_after_seconds=180,
        missing_confirm_polls=4,
        near_arrival_m=400.0,
    )


def monitor(tmp_path: Path, settings: Settings, trip: Voyage) -> Monitor:
    return Monitor(
        settings,
        Calibration(Offset(-86, 0, 83, 14), 3440, 1440, "icon_template.png"),
        readout=None,
        outbox=Outbox([Channel("discord")]),
        voyage=trip,
        samples_dir=tmp_path,
    )


class TestRetune:
    def test_retune_changes_the_stuck_threshold(self):
        trip = voyage()
        trip.update(2000, now=0)
        assert trip.update(2000, now=100).state is State.TRAVELLING

        trip.retune(stuck_after_seconds=60)
        assert trip.update(2000, now=130).state is State.STUCK

    def test_retune_keeps_the_journey(self):
        trip = voyage()
        trip.update(2000, now=0)
        trip.update(2000, now=90)

        trip.retune(stuck_after_seconds=60)
        status = trip.update(2000, now=120)
        assert status.distance_m == 2000
        assert status.stalled_seconds >= 120

    def test_retune_changes_the_arrival_threshold(self):
        trip = voyage()
        trip.update(500, now=0)
        assert trip.update(90, now=30).state is State.TRAVELLING

        trip.retune(arrival_threshold_m=100, arrival_confirm_polls=1)
        assert trip.update(90, now=60).state is State.ARRIVED

    def test_retune_ignores_what_it_is_not_given(self):
        trip = voyage()
        trip.update(2000, now=0)
        trip.retune(approaching_m=800)
        assert trip.update(2000, now=190).state is State.STUCK


class TestApply:
    def test_apply_swaps_the_outbox(self, tmp_path):
        watcher = monitor(tmp_path, Settings(samples_enabled=False), voyage())
        replacement = Outbox([Channel("desktop")])
        watcher.apply(Settings(samples_enabled=False), replacement)
        assert watcher.outbox is replacement
        assert watcher.outbox.names == ["desktop"]

    def test_apply_changes_the_poll_interval(self, tmp_path):
        watcher = monitor(tmp_path, Settings(poll_interval_seconds=30), voyage())
        watcher.apply(Settings(poll_interval_seconds=5), Outbox([]))
        assert watcher._settings.poll_interval_seconds == 5

    def test_apply_retunes_the_voyage_in_place(self, tmp_path):
        trip = voyage()
        watcher = monitor(tmp_path, Settings(samples_enabled=False), trip)
        trip.update(2000, now=0)
        trip.update(2000, now=90)

        watcher.apply(Settings(stuck_after_seconds=60, samples_enabled=False), Outbox([]))
        status = trip.update(2000, now=120)
        assert status.state is State.STUCK
        assert status.distance_m == 2000

    def test_apply_drops_the_marker_so_it_is_rebuilt(self, tmp_path):
        watcher = monitor(tmp_path, Settings(match_threshold=0.85), voyage())
        watcher._marker = object()
        watcher._marker_size = (3440, 1440)

        watcher.apply(Settings(match_threshold=0.95), Outbox([]))
        assert watcher._marker is None
        assert watcher._marker_size is None

    def test_apply_resizes_the_timers(self, tmp_path):
        watcher = monitor(tmp_path, Settings(heartbeat_minutes=1), voyage())
        watcher.apply(Settings(heartbeat_minutes=5, stuck_realert_minutes=2), Outbox([]))
        assert watcher._heartbeat.interval == 300
        assert watcher._nagging.interval == 120

    def test_apply_keeps_when_the_timers_last_fired(self, tmp_path):
        watcher = monitor(tmp_path, Settings(heartbeat_minutes=1), voyage())
        watcher._heartbeat.mark(1000.0)
        watcher.apply(Settings(heartbeat_minutes=5), Outbox([]))
        assert watcher._heartbeat.last_at == 1000.0


class TestFacts:
    def status(self, state=State.TRAVELLING, distance=3170.0, eta=600.0, stalled=0.0) -> Status:
        return Status(state, distance, eta, stalled, None)

    def facts(self, **overrides) -> Facts:
        settings = {"channels": ["discord", "desktop"], "muted": False, "paused": False}
        settings.update(overrides)
        facts = Facts()
        facts.update(self.status(**settings.pop("status", {})), **settings)
        return facts

    def test_headline_follows_the_state(self):
        assert self.facts().headline == "Under way"

    def test_headline_says_paused_over_anything_else(self):
        assert self.facts(paused=True).headline == "Paused"

    def test_distance_reads_plainly(self):
        assert self.facts().distance == "3170m remaining"

    def test_distance_copes_with_nothing_read(self):
        facts = Facts()
        facts.update(self.status(distance=None), channels=[], muted=False, paused=False)
        assert facts.distance == "Distance unknown"

    def test_timing_prefers_a_stall_over_an_eta(self):
        facts = Facts()
        facts.update(self.status(stalled=65.0), channels=[], muted=False, paused=False)
        assert facts.timing == "No progress for 1m 5s"

    def test_timing_reports_the_eta_while_moving(self):
        assert self.facts().timing == "About 10m 0s to go"

    def test_delivery_names_the_channels(self):
        assert self.facts().delivery == "Alerting discord and desktop"

    def test_delivery_says_when_muted(self):
        assert self.facts(muted=True).delivery == "Notifications muted"

    def test_delivery_warns_when_there_is_nowhere_to_send(self):
        assert self.facts(channels=[]).delivery == "Nowhere to send alerts"

    def test_the_tooltip_carries_every_line(self):
        tooltip = self.facts().tooltip
        assert "BDO Autoroute Track" in tooltip
        assert "3170m remaining" in tooltip
        assert "checked" in tooltip


class TestIcons:
    def test_every_state_has_its_own_colour(self):
        from bdo_autoroute.icons import for_state

        colours = {state: for_state(state).getpixel((32, 46)) for state in State}
        assert len(set(colours.values())) >= 4

    def test_muting_greys_the_icon(self):
        from bdo_autoroute.icons import for_state

        assert for_state(State.STUCK).getpixel((32, 46)) != for_state(
            State.STUCK, muted=True
        ).getpixel((32, 46))

    def test_the_tray_has_an_icon_for_every_case(self):
        from bdo_autoroute.icons import every_state

        assert len(every_state()) == len(State) * 2


class TestReloadsFromDisk:
    """A save from anywhere reaches a running monitor.

    Without this, a save from settings.cmd would not reach a tray started
    separately, and the dialog would have to tell people to restart.
    """

    def monitor_watching(self, tmp_path, config, loads):
        watcher = monitor(tmp_path, Settings(samples_enabled=False), voyage())
        watcher.reloads_from(config, loads)
        return watcher

    def config(self, tmp_path, interval=30):
        path = tmp_path / "config.toml"
        path.write_text(f"[capture]\npoll_interval_seconds = {interval}\n", encoding="utf-8")
        return path

    def test_an_untouched_file_is_not_reloaded(self, tmp_path):
        reloads = []
        config = self.config(tmp_path)

        def loads():
            reloads.append(1)
            return Settings.load(config), Outbox([])

        watcher = self.monitor_watching(tmp_path, config, loads)
        watcher._reload_if_changed()
        watcher._reload_if_changed()
        assert reloads == []

    def test_a_changed_file_is_adopted(self, tmp_path):
        config = self.config(tmp_path, interval=30)

        def loads():
            return Settings.load(config), Outbox([])

        watcher = self.monitor_watching(tmp_path, config, loads)
        assert watcher._settings.poll_interval_seconds == 30

        import os
        import time

        config.write_text("[capture]\npoll_interval_seconds = 5\n", encoding="utf-8")
        os.utime(config, (time.time() + 10, time.time() + 10))

        watcher._reload_if_changed()
        assert watcher._settings.poll_interval_seconds == 5

    def test_a_broken_file_does_not_stop_the_monitor(self, tmp_path, caplog):
        config = self.config(tmp_path)

        def loads():
            raise ValueError("not valid TOML")

        watcher = self.monitor_watching(tmp_path, config, loads)

        import os
        import time

        config.write_text("nonsense {", encoding="utf-8")
        os.utime(config, (time.time() + 10, time.time() + 10))

        watcher._reload_if_changed()
        assert "could not be loaded" in caplog.text
        assert watcher._settings.poll_interval_seconds == 30

    def test_nothing_happens_without_a_watched_file(self, tmp_path):
        monitor(tmp_path, Settings(), voyage())._reload_if_changed()
