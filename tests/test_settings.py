"""Settings: defaults, TOML section mapping, and what counts as invalid."""

from __future__ import annotations

import pytest

from bdo_autoroute.settings import Settings, SettingsError


def loaded(toml: str, tmp_path) -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")
    return Settings.load(path)


class TestLogging:
    def test_log_to_file_is_off_unless_asked_for(self):
        assert Settings().log_to_file is False

    def test_load_reads_the_logging_section(self, tmp_path):
        settings = loaded(
            "[logging]\nto_file = true\nmax_mb = 10\nkeep_files = 2\n", tmp_path
        )
        assert settings.log_to_file is True
        assert settings.log_max_mb == 10
        assert settings.log_keep_files == 2

    def test_log_max_bytes_converts_megabytes(self):
        assert Settings(log_max_mb=2).log_max_bytes == 2_000_000

    def test_load_rejects_a_zero_sized_log(self, tmp_path):
        with pytest.raises(SettingsError, match="max_mb"):
            loaded("[logging]\nmax_mb = 0\n", tmp_path)

    def test_load_rejects_a_negative_backup_count(self, tmp_path):
        with pytest.raises(SettingsError, match="keep_files"):
            loaded("[logging]\nkeep_files = -1\n", tmp_path)

    def test_keeping_no_backups_is_allowed(self, tmp_path):
        assert loaded("[logging]\nkeep_files = 0\n", tmp_path).log_keep_files == 0


class TestDefaults:
    def test_load_falls_back_to_defaults_for_an_empty_config(self, tmp_path):
        settings = loaded("", tmp_path)
        assert settings.capture_method == "window"
        assert settings.poll_interval_seconds == 30
        assert settings.arrival_threshold_m == 70.0
        assert settings.brightness_threshold == 120

    def test_load_complains_about_a_missing_file(self, tmp_path):
        with pytest.raises(SettingsError, match="No config"):
            Settings.load(tmp_path / "nowhere.toml")


class TestValidation:
    def test_load_rejects_an_unknown_capture_method(self, tmp_path):
        with pytest.raises(SettingsError, match="capture.method"):
            loaded('[capture]\nmethod = "telepathy"\n', tmp_path)

    def test_load_rejects_an_unknown_ocr_backend(self, tmp_path):
        with pytest.raises(SettingsError, match="ocr.backend"):
            loaded('[ocr]\nbackend = "guesswork"\n', tmp_path)

    def test_load_rejects_a_match_threshold_outside_zero_to_one(self, tmp_path):
        with pytest.raises(SettingsError, match="match_threshold"):
            loaded("[marker]\nmatch_threshold = 1.5\n", tmp_path)

    def test_load_rejects_a_sub_second_poll(self, tmp_path):
        with pytest.raises(SettingsError, match="poll_interval_seconds"):
            loaded("[capture]\npoll_interval_seconds = 0\n", tmp_path)

    def test_load_rejects_negative_retention(self, tmp_path):
        with pytest.raises(SettingsError, match="retain_days"):
            loaded("[storage]\nretain_days = -1\n", tmp_path)


class TestDerivedValues:
    def test_heartbeat_seconds_converts_minutes(self):
        assert Settings(heartbeat_minutes=1).heartbeat_seconds == 60

    def test_stuck_realert_seconds_converts_minutes(self):
        assert Settings(stuck_realert_minutes=10).stuck_realert_seconds == 600

    def test_sample_interval_seconds_converts_minutes(self):
        assert Settings(sample_every_minutes=30).sample_interval_seconds == 1800


class TestArgumentParsing:
    """-v and --log must work on either side of the subcommand."""

    def parse(self, argv):
        from bdo_autoroute.cli import parser

        return parser().parse_args(argv)

    def asked_for_log(self, argv) -> bool:
        return getattr(self.parse(argv), "log", False)

    def test_log_is_accepted_after_the_subcommand(self):
        assert self.asked_for_log(["run", "--log"])

    def test_log_is_accepted_before_the_subcommand(self):
        assert self.asked_for_log(["--log", "run"])

    def test_log_defaults_to_off(self):
        assert not self.asked_for_log(["run"])

    def test_verbose_is_accepted_after_the_subcommand(self):
        assert getattr(self.parse(["shot", "-v"]), "verbose", False)

    def test_verbose_is_accepted_before_the_subcommand(self):
        assert getattr(self.parse(["-v", "shot"]), "verbose", False)

    def test_once_still_belongs_to_run(self):
        assert self.parse(["run", "--once", "--log"]).once is True
