"""Outbox: alerts reach every channel, and a dead channel says so.

A monitor that has quietly stopped notifying looks exactly like one with
nothing to report, so silent delivery failure is the worst outcome available.
"""

from __future__ import annotations

import pytest

from bdo_autoroute.alerts import Alert
from bdo_autoroute.outbox import FAILURES_BEFORE_COMPLAINT, Outbox
from bdo_autoroute.voyage import State


def alert() -> Alert:
    return Alert(headline="Looks stuck", body="3580m remaining.", state=State.STUCK, urgent=True)


class Channel:
    def __init__(self, name: str, *, accepts: bool = True, raises: bool = False) -> None:
        self.name = name
        self.accepts = accepts
        self.raises = raises
        self.received: list[Alert] = []

    def deliver(self, alert: Alert) -> bool:
        if self.raises:
            raise RuntimeError("boom")
        self.received.append(alert)
        return self.accepts


class TestDeliver:
    def test_deliver_reaches_every_channel(self):
        first, second = Channel("discord"), Channel("desktop")
        assert Outbox([first, second]).deliver(alert())
        assert len(first.received) == 1
        assert len(second.received) == 1

    def test_deliver_succeeds_when_any_channel_accepts(self):
        outbox = Outbox([Channel("discord", accepts=False), Channel("desktop")])
        assert outbox.deliver(alert())

    def test_deliver_fails_only_when_all_channels_fail(self):
        outbox = Outbox([Channel("discord", accepts=False), Channel("desktop", accepts=False)])
        assert not outbox.deliver(alert())

    def test_deliver_keeps_going_when_a_channel_raises(self):
        healthy = Channel("desktop")
        assert Outbox([Channel("discord", raises=True), healthy]).deliver(alert())
        assert len(healthy.received) == 1

    def test_deliver_is_false_for_an_empty_outbox(self):
        assert not Outbox([]).deliver(alert())


class TestComplaints:
    def test_a_repeatedly_failing_channel_is_reported(self, caplog):
        outbox = Outbox([Channel("discord", accepts=False)])
        for _ in range(FAILURES_BEFORE_COMPLAINT):
            outbox.deliver(alert())
        assert "failed 3 deliveries in a row" in caplog.text

    def test_a_single_failure_is_not_reported(self, caplog):
        Outbox([Channel("discord", accepts=False)]).deliver(alert())
        assert "in a row" not in caplog.text

    def test_recovery_is_reported(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        channel = Channel("discord", accepts=False)
        outbox = Outbox([channel])
        for _ in range(FAILURES_BEFORE_COMPLAINT):
            outbox.deliver(alert())

        channel.accepts = True
        outbox.deliver(alert())
        assert "delivering again" in caplog.text

    def test_reaching_nobody_is_an_error(self, caplog):
        Outbox([Channel("discord", accepts=False)]).deliver(alert())
        assert "reached nobody" in caplog.text

    def test_the_count_resets_after_a_success(self, caplog):
        channel = Channel("discord", accepts=False)
        outbox = Outbox([channel])
        outbox.deliver(alert())
        outbox.deliver(alert())

        channel.accepts = True
        outbox.deliver(alert())
        channel.accepts = False
        outbox.deliver(alert())
        assert "in a row" not in caplog.text


class TestNames:
    def test_names_lists_the_channels(self):
        assert Outbox([Channel("discord"), Channel("desktop")]).names == ["discord", "desktop"]

    def test_empty_reports_whether_anything_is_configured(self):
        assert Outbox([]).empty
        assert not Outbox([Channel("desktop")]).empty


class TestThumbnail:
    def test_thumbnail_is_none_without_a_screenshot(self):
        assert alert().thumbnail(480) is None

    def test_thumbnail_shrinks_a_large_screenshot(self):
        from PIL import Image

        shown = alert().showing(Image.new("RGB", (3440, 1440)))
        assert shown.thumbnail(480).size == (480, 201)

    def test_thumbnail_leaves_a_small_screenshot_alone(self):
        from PIL import Image

        shown = alert().showing(Image.new("RGB", (200, 100)))
        assert shown.thumbnail(480).size == (200, 100)


@pytest.mark.parametrize("channels", [["discord"], ["desktop"], ["discord", "desktop"]])
def test_settings_accept_the_known_channels(channels, tmp_path):
    from bdo_autoroute.settings import Settings

    path = tmp_path / "config.toml"
    path.write_text(f"[notify]\nchannels = {channels!r}\n", encoding="utf-8")
    assert Settings.load(path).channels == channels


def test_settings_reject_an_unknown_channel(tmp_path):
    from bdo_autoroute.settings import Settings, SettingsError

    path = tmp_path / "config.toml"
    path.write_text('[notify]\nchannels = ["carrier-pigeon"]\n', encoding="utf-8")
    with pytest.raises(SettingsError, match="carrier-pigeon"):
        Settings.load(path)


class TestSilencingOneChannel:
    """Turning off Discord must not turn off the Windows toast, and neither
    should look like a broken channel.
    """

    def outbox(self) -> tuple[Outbox, Channel, Channel]:
        discord, desktop = Channel("discord"), Channel("desktop")
        return Outbox([discord, desktop]), discord, desktop

    def test_a_silenced_channel_is_skipped(self):
        box, discord, desktop = self.outbox()
        box.silence("discord")
        assert box.deliver(alert())
        assert discord.received == []
        assert len(desktop.received) == 1

    def test_the_others_keep_working(self):
        box, _discord, desktop = self.outbox()
        box.silence("discord")
        box.deliver(alert())
        box.deliver(alert())
        assert len(desktop.received) == 2

    def test_silencing_can_be_undone(self):
        box, discord, _desktop = self.outbox()
        box.silence("discord")
        box.deliver(alert())
        box.silence("discord", False)
        box.deliver(alert())
        assert len(discord.received) == 1

    def test_silencing_everything_delivers_nothing(self):
        box, discord, desktop = self.outbox()
        box.silence("discord")
        box.silence("desktop")
        assert not box.deliver(alert())
        assert discord.received == [] and desktop.received == []

    def test_a_silenced_channel_is_never_called_broken(self, caplog):
        box, _discord, _desktop = self.outbox()
        box.silence("discord")
        box.silence("desktop")
        for _ in range(FAILURES_BEFORE_COMPLAINT + 2):
            box.deliver(alert())
        assert "in a row" not in caplog.text
        assert "reached nobody" not in caplog.text

    def test_resuming_clears_an_earlier_failure_count(self):
        failing = Channel("discord", accepts=False)
        box = Outbox([failing])
        box.deliver(alert())
        box.deliver(alert())
        box.silence("discord")
        box.silence("discord", False)
        failing.accepts = True
        assert box.deliver(alert())

    def test_has_reports_which_channels_exist(self):
        box, _discord, _desktop = self.outbox()
        assert box.has("discord") and box.has("desktop")
        assert not box.has("carrier-pigeon")

    def test_a_channel_that_was_never_built_is_not_offered(self):
        """Discord only exists when a webhook is configured."""
        assert not Outbox([Channel("desktop")]).has("discord")

    def test_nothing_starts_silenced(self):
        box, _discord, _desktop = self.outbox()
        assert not box.silenced("discord")
        assert not box.silenced("desktop")
