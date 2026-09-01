"""How much each channel wants to hear.

A toast every minute teaches you to dismiss toasts without reading them, which
costs you the one that mattered. Desktop therefore defaults to important-only
while Discord keeps hearing everything, because the heartbeat on a phone is what
proves the monitor is still alive.

The distinction that matters here: a channel skipping a routine alert has not
failed. Counting a skip as a delivery failure would trip the dead-channel
warning after three heartbeats.
"""

from __future__ import annotations

import pytest

from bdo_autoroute.alerts import Alert
from bdo_autoroute.outbox import FAILURES_BEFORE_COMPLAINT, IMPORTANT, VERBOSE, Outbox
from bdo_autoroute.settings import Settings, SettingsError
from bdo_autoroute.voyage import State, Status


def status(state=State.TRAVELLING, distance=3720.0, eta=400.0, stalled=0.0) -> Status:
    return Status(state, distance, eta, stalled, None)


class Channel:
    def __init__(self, name: str, sends: bool = True) -> None:
        self.name = name
        self.sends = sends
        self.received: list[str] = []

    def deliver(self, alert: Alert) -> bool:
        self.received.append(alert.headline)
        return self.sends


class TestRoutine:
    def test_routine_covers_the_heartbeat(self):
        assert Alert.heartbeat(status()).routine

    def test_routine_covers_the_opening_line(self):
        assert Alert.watching(status()).routine

    def test_routine_excludes_a_stall(self):
        assert not Alert.stalling(status(stalled=65.0)).routine

    def test_routine_excludes_being_stuck(self):
        assert not Alert.still_stuck(status(stalled=200.0)).routine

    def test_routine_excludes_approaching(self):
        assert not Alert.approaching(status(distance=420.0)).routine

    def test_routine_follows_the_configured_urgent_states(self):
        from bdo_autoroute.voyage import Event

        arrival = Event(State.ARRIVED, State.TRAVELLING, "Arrived.", 41.0, None, False)
        assert not Alert.for_event(arrival, urgent_states=["ARRIVED"]).routine
        assert Alert.for_event(arrival, urgent_states=[]).routine


class TestCarries:
    def outbox(self, **modes) -> Outbox:
        return Outbox([Channel("discord"), Channel("desktop")], modes)

    def test_mode_defaults_to_verbose(self):
        assert Outbox([Channel("desktop")]).mode("desktop") == VERBOSE

    def test_carries_everything_when_verbose(self):
        outbox = self.outbox(desktop=VERBOSE)
        assert outbox.carries("desktop", Alert.heartbeat(status()))

    def test_carries_drops_a_routine_alert_when_important_only(self):
        outbox = self.outbox(desktop=IMPORTANT)
        assert not outbox.carries("desktop", Alert.heartbeat(status()))

    def test_carries_keeps_a_real_alert_when_important_only(self):
        outbox = self.outbox(desktop=IMPORTANT)
        assert outbox.carries("desktop", Alert.still_stuck(status(stalled=200.0)))

    def test_set_mode_takes_effect_without_rebuilding(self):
        outbox = self.outbox(desktop=VERBOSE)
        outbox.set_mode("desktop", IMPORTANT)
        assert not outbox.carries("desktop", Alert.heartbeat(status()))


class TestDeliveryByMode:
    def channels(self):
        return Channel("discord"), Channel("desktop")

    def test_a_heartbeat_reaches_only_the_verbose_channel(self):
        discord, desktop = self.channels()
        outbox = Outbox([discord, desktop], {"discord": VERBOSE, "desktop": IMPORTANT})
        outbox.deliver(Alert.heartbeat(status()))
        assert discord.received == ["Still under way"]
        assert desktop.received == []

    def test_being_stuck_reaches_both(self):
        discord, desktop = self.channels()
        outbox = Outbox([discord, desktop], {"discord": VERBOSE, "desktop": IMPORTANT})
        outbox.deliver(Alert.still_stuck(status(stalled=200.0)))
        assert discord.received == ["Still stuck"]
        assert desktop.received == ["Still stuck"]

    def test_a_skipped_routine_alert_reports_nothing_delivered(self):
        desktop = Channel("desktop")
        outbox = Outbox([desktop], {"desktop": IMPORTANT})
        assert outbox.deliver(Alert.heartbeat(status())) is False

    def test_skipping_is_not_a_delivery_failure(self):
        """The dead-channel warning must not fire because of the mode.

        Three skipped heartbeats look identical to three failed ones unless
        the mode filter runs before anything is counted.
        """
        desktop = Channel("desktop")
        outbox = Outbox([desktop], {"desktop": IMPORTANT})
        for _ in range(FAILURES_BEFORE_COMPLAINT + 1):
            outbox.deliver(Alert.heartbeat(status()))

        desktop.sends = False
        outbox.deliver(Alert.still_stuck(status(stalled=200.0)))
        assert outbox._failures["desktop"] == 1

    def test_a_silenced_channel_is_still_silent_in_verbose(self):
        desktop = Channel("desktop")
        outbox = Outbox([desktop], {"desktop": VERBOSE})
        outbox.silence("desktop")
        outbox.deliver(Alert.still_stuck(status(stalled=200.0)))
        assert desktop.received == []


class TestFootnote:
    def test_footnote_carries_the_eta(self):
        assert "ETA 6m 40s" in Alert.heartbeat(status()).footnote

    def test_footnote_ends_with_the_time_and_no_label(self):
        footnote = Alert.heartbeat(status()).footnote
        assert "Time " not in footnote
        assert footnote.split(" · ")[-1].count(":") == 2

    def test_footnote_is_just_the_time_when_there_are_no_details(self):
        assert " · " not in Alert.stalling(status(stalled=65.0)).footnote


class TestSettings:
    def test_desktop_defaults_to_important(self):
        assert Settings().desktop_mode == "important"

    def test_discord_defaults_to_verbose(self):
        assert Settings().discord_mode == "verbose"

    def test_notification_modes_is_keyed_by_channel(self):
        assert Settings().notification_modes == {
            "discord": "verbose",
            "desktop": "important",
        }

    def test_an_unknown_mode_is_refused(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[notify]\ndesktop_mode = "loud"\n', encoding="utf-8")
        with pytest.raises(SettingsError, match="desktop_mode"):
            Settings.load(path)

    def test_a_mode_survives_a_round_trip(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[notify]\ndesktop_mode = "verbose"\n', encoding="utf-8")
        assert Settings.load(path).desktop_mode == "verbose"
