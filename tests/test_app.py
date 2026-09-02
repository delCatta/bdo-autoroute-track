"""The window's first face is a checklist. This is what it checks."""

from __future__ import annotations

from pathlib import Path

from bdo_autoroute.app import Checklist
from bdo_autoroute.cli import DEFAULT_COMMAND, arguments
from bdo_autoroute.commands import Fit
from bdo_autoroute.readout import Reading

DESKTOP_ONLY = '[notify]\nchannels = ["desktop"]\n'
DISCORD_WIRED = (
    '[notify]\nchannels = ["discord"]\n'
    'discord_webhook_url = "https://discord.com/api/webhooks/1/abc"\n'
)
DISCORD_BLANK = '[notify]\nchannels = ["discord"]\ndiscord_webhook_url = ""\n'


def checklist(tmp_path: Path, toml: str | None = None, *, calibrated: bool = False) -> Checklist:
    config = tmp_path / "config.toml"
    if toml is not None:
        config.write_text(toml, encoding="utf-8")
    calibration = tmp_path / "calibration.json"
    icon = tmp_path / "icon_template.png"
    if calibrated:
        calibration.write_text("{}", encoding="utf-8")
        icon.write_bytes(b"")
    return Checklist(config=config, calibration=calibration, icon=icon)


class TestReachable:
    def test_reachable_is_false_without_a_config(self, tmp_path):
        assert not checklist(tmp_path).reachable

    def test_reachable_with_windows_notifications_alone(self, tmp_path):
        assert checklist(tmp_path, DESKTOP_ONLY).reachable

    def test_reachable_with_discord_and_a_webhook(self, tmp_path):
        assert checklist(tmp_path, DISCORD_WIRED).reachable

    def test_discord_without_a_webhook_reaches_nobody(self, tmp_path):
        assert not checklist(tmp_path, DISCORD_BLANK).reachable


class TestCalibrated:
    def test_calibrated_needs_both_files(self, tmp_path):
        partial = checklist(tmp_path, DESKTOP_ONLY)
        (tmp_path / "calibration.json").write_text("{}", encoding="utf-8")
        assert not partial.calibrated

    def test_calibrated_when_both_are_there(self, tmp_path):
        assert checklist(tmp_path, DESKTOP_ONLY, calibrated=True).calibrated


class TestNextStep:
    def test_next_step_starts_with_alerts(self, tmp_path):
        assert checklist(tmp_path).next_step == "Choose where alerts go."

    def test_next_step_then_asks_for_the_marker(self, tmp_path):
        assert checklist(tmp_path, DESKTOP_ONLY).next_step == "Show it the marker."

    def test_ready_once_both_are_done(self, tmp_path):
        done = checklist(tmp_path, DESKTOP_ONLY, calibrated=True)
        assert done.ready
        assert done.next_step == "Ready."


class TestArguments:
    def test_arguments_opens_the_window_when_nothing_is_asked(self):
        assert arguments([]) == [DEFAULT_COMMAND]

    def test_arguments_leaves_a_request_alone(self):
        assert arguments(["run", "--once"]) == ["run", "--once"]


class TestFit:
    def test_summary_reports_the_distance_when_read(self):
        assert Fit(0.94, Reading(10820.0, "10820")).summary.startswith("Read 10820m.")

    def test_summary_says_what_ocr_saw_when_it_could_not(self):
        fit = Fit(0.94, Reading(None, "/40"))
        assert not fit.ok
        assert "'/40'" in fit.summary
