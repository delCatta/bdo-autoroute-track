"""Two things the user must be able to control: what leaves, and whether it does.

A full game window carries whispers, guild chat, the character name and the
marketplace. Fine in a private Discord channel, a leak in a shared one. And a
tray app that cannot be told to be quiet is a tray app people close.
"""

from __future__ import annotations

import pytest
from PIL import Image

from bdo_autoroute.alerts import Alert
from bdo_autoroute.marker import Box, Sighting
from bdo_autoroute.observation import Observation
from bdo_autoroute.outbox import FAILURES_BEFORE_COMPLAINT, Outbox
from bdo_autoroute.settings import MARKER_CROP_MARGIN, Settings, SettingsError
from bdo_autoroute.voyage import State


def frame() -> Image.Image:
    return Image.new("RGB", (3440, 1440), (20, 20, 30))


def seen() -> Observation:
    return Observation(
        frame(),
        Sighting(0.97, Box(1700, 1080, 17, 16), Box(1614, 1080, 83, 14)),
    )


def loaded(toml: str, tmp_path) -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")
    return Settings.load(path)


class TestScreenshotSetting:
    def test_screenshot_defaults_to_full(self):
        assert Settings().screenshot == "full"

    @pytest.mark.parametrize("mode", ["full", "marker", "none"])
    def test_load_accepts_every_mode(self, mode, tmp_path):
        assert loaded(f'[notify]\nscreenshot = "{mode}"\n', tmp_path).screenshot == mode

    def test_load_rejects_an_unknown_mode(self, tmp_path):
        with pytest.raises(SettingsError, match="notify.screenshot"):
            loaded('[notify]\nscreenshot = "everything"\n', tmp_path)

    def test_wants_screenshot_is_false_only_for_none(self):
        assert Settings(screenshot="full").wants_screenshot
        assert Settings(screenshot="marker").wants_screenshot
        assert not Settings(screenshot="none").wants_screenshot

    def test_crops_screenshot_is_true_only_for_marker(self):
        assert Settings(screenshot="marker").crops_screenshot
        assert not Settings(screenshot="full").crops_screenshot

    def test_the_old_boolean_still_works(self, tmp_path):
        assert loaded("[notify]\nattach_screenshot = true\n", tmp_path).screenshot == "full"
        assert loaded("[notify]\nattach_screenshot = false\n", tmp_path).screenshot == "none"


class TestNeighbourhood:
    def test_neighbourhood_is_far_smaller_than_the_window(self):
        cropped = seen().neighbourhood(MARKER_CROP_MARGIN)
        assert cropped.width < 3440 / 4
        assert cropped.height < 1440 / 4

    def test_neighbourhood_covers_both_the_icon_and_the_digits(self):
        cropped = seen().neighbourhood(MARKER_CROP_MARGIN)
        assert cropped.width >= (1700 + 17) - 1614

    def test_neighbourhood_stays_inside_the_frame(self):
        edge = Observation(frame(), Sighting(0.97, Box(0, 0, 17, 16), Box(0, 0, 83, 14)))
        cropped = edge.neighbourhood(MARKER_CROP_MARGIN)
        assert cropped.width > 0 and cropped.height > 0

    def test_neighbourhood_is_none_without_a_sighting(self):
        assert Observation(frame()).neighbourhood(MARKER_CROP_MARGIN) is None


class TestMute:
    def alert(self) -> Alert:
        return Alert("Looks stuck", "3580m remaining.", State.STUCK, urgent=True)

    class Channel:
        name = "desktop"

        def __init__(self) -> None:
            self.received = []

        def deliver(self, alert) -> bool:
            self.received.append(alert)
            return True

    def test_switching_every_channel_off_stops_delivery(self):
        channel = self.Channel()
        outbox = Outbox([channel])
        outbox.silence("desktop")
        assert not outbox.deliver(self.alert())
        assert channel.received == []

    def test_switching_one_back_on_resumes_delivery(self):
        channel = self.Channel()
        outbox = Outbox([channel])
        outbox.silence("desktop")
        outbox.deliver(self.alert())
        outbox.silence("desktop", False)
        assert outbox.deliver(self.alert())
        assert len(channel.received) == 1

    def test_being_quiet_is_never_counted_as_a_broken_channel(self, caplog):
        outbox = Outbox([self.Channel()])
        outbox.silence("desktop")
        for _ in range(FAILURES_BEFORE_COMPLAINT + 2):
            outbox.deliver(self.alert())
        assert "in a row" not in caplog.text
        assert "reached nobody" not in caplog.text

    def test_muted_means_every_channel_is_off(self):
        outbox = Outbox([self.Channel()])
        assert not outbox.muted
        outbox.silence("desktop")
        assert outbox.muted

    def test_an_empty_outbox_is_not_muted(self):
        """Nowhere to send is a different problem from choosing silence."""
        assert not Outbox([]).muted


class TestResolutionBlame:
    """A scaled template scores 0.00 and says only 'marker not found'.

    Seen live: the window went 3440x1440 -> 1846x1031 and the tool went blind
    with nothing in the log pointing at why.
    """

    def monitor(self, tmp_path, calibrated=(3440, 1440)):
        from bdo_autoroute.marker import Offset
        from bdo_autoroute.monitor import Monitor
        from bdo_autoroute.settings import Calibration

        return Monitor(
            Settings(samples_enabled=False, missing_confirm_polls=4),
            Calibration(Offset(-86, 0, 83, 14), *calibrated, "icon_template.png"),
            readout=None,
            outbox=None,
            voyage=None,
            samples_dir=tmp_path,
        )

    def test_a_changed_resolution_is_blamed_after_enough_misses(self, tmp_path, caplog):
        watcher = self.monitor(tmp_path)
        for _ in range(4):
            watcher._note_miss(True, (1846, 1031))
        assert "Re-run calibrate" in caplog.text

    def test_it_is_said_once_not_every_poll(self, tmp_path, caplog):
        watcher = self.monitor(tmp_path)
        for _ in range(12):
            watcher._note_miss(True, (1846, 1031))
        assert caplog.text.count("Re-run calibrate") == 1

    def test_the_same_resolution_is_never_blamed(self, tmp_path, caplog):
        watcher = self.monitor(tmp_path)
        for _ in range(12):
            watcher._note_miss(True, (3440, 1440))
        assert "Re-run calibrate" not in caplog.text

    def test_a_few_misses_are_not_enough(self, tmp_path, caplog):
        watcher = self.monitor(tmp_path)
        for _ in range(3):
            watcher._note_miss(True, (1846, 1031))
        assert "Re-run calibrate" not in caplog.text

    def test_a_sighting_resets_the_count(self, tmp_path, caplog):
        watcher = self.monitor(tmp_path)
        for _ in range(3):
            watcher._note_miss(True, (1846, 1031))
        watcher._note_miss(False, (1846, 1031))
        for _ in range(3):
            watcher._note_miss(True, (1846, 1031))
        assert "Re-run calibrate" not in caplog.text
