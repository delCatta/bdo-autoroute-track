"""Editing config.toml without destroying it.

Every setting is explained by a comment above it, and those comments are most of
the file's value. A round trip through a TOML library would rewrite the file and
throw them away.
"""

from __future__ import annotations

import pytest

from bdo_autoroute.configfile import ConfigFile, as_toml
from bdo_autoroute.vault import PREFIX, masked, protected, revealed

SAMPLE = """\
# BDO Autoroute Track - configuration

[capture]
# How often to read the number, in seconds.
poll_interval_seconds = 30

[notify]
# Where alerts go.
channels = ["discord", "desktop"]

# Create one under Channel > Integrations > Webhooks.
discord_webhook_url = ""

# Ping so your phone buzzes.
mention = ""
"""


def written(tmp_path, text=SAMPLE):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestAsToml:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, "true"),
            (False, "false"),
            (30, "30"),
            (70.0, "70.0"),
            ("hello", '"hello"'),
            (["discord", "desktop"], '["discord", "desktop"]'),
            ([], "[]"),
        ],
    )
    def test_as_toml_renders_python_values(self, value, expected):
        assert as_toml(value) == expected

    def test_as_toml_escapes_quotes(self):
        assert as_toml('a "quoted" thing') == '"a \\"quoted\\" thing"'


class TestSet:
    def test_set_replaces_a_value_in_place(self, tmp_path):
        path = written(tmp_path)
        config = ConfigFile(path)
        config.set("capture", "poll_interval_seconds", 15)
        config.save()
        assert "poll_interval_seconds = 15" in path.read_text(encoding="utf-8")

    def test_set_keeps_every_comment(self, tmp_path):
        path = written(tmp_path)
        config = ConfigFile(path)
        config.set("notify", "mention", "<@123>")
        config.save()

        text = path.read_text(encoding="utf-8")
        assert "# Ping so your phone buzzes." in text
        assert "# Create one under Channel > Integrations > Webhooks." in text
        assert "# BDO Autoroute Track - configuration" in text

    def test_set_only_touches_the_named_section(self, tmp_path):
        path = written(
            tmp_path,
            "[a]\nvalue = 1\n\n[b]\nvalue = 2\n",
        )
        config = ConfigFile(path)
        config.set("b", "value", 99)
        config.save()

        text = path.read_text(encoding="utf-8")
        assert "[a]\nvalue = 1" in text
        assert "value = 99" in text

    def test_set_writes_a_list(self, tmp_path):
        path = written(tmp_path)
        config = ConfigFile(path)
        config.set("notify", "channels", ["desktop"])
        config.save()
        assert 'channels = ["desktop"]' in path.read_text(encoding="utf-8")

    def test_set_adds_a_key_that_was_missing(self, tmp_path):
        path = written(tmp_path)
        config = ConfigFile(path)
        config.set("notify", "screenshot", "marker")
        config.save()

        text = path.read_text(encoding="utf-8")
        assert 'screenshot = "marker"' in text
        assert "# Ping so your phone buzzes." in text

    def test_set_adds_a_section_that_was_missing(self, tmp_path):
        path = written(tmp_path)
        config = ConfigFile(path)
        config.set("logging", "to_file", True)
        config.save()

        text = path.read_text(encoding="utf-8")
        assert "[logging]" in text
        assert "to_file = true" in text

    def test_the_result_still_parses(self, tmp_path):
        from bdo_autoroute.settings import Settings

        path = written(tmp_path)
        config = ConfigFile(path)
        config.set("notify", "channels", ["desktop"])
        config.set("notify", "screenshot", "marker")
        config.set("capture", "poll_interval_seconds", 45)
        config.save()

        settings = Settings.load(path)
        assert settings.channels == ["desktop"]
        assert settings.screenshot == "marker"
        assert settings.poll_interval_seconds == 45

    def test_crlf_files_stay_crlf(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(SAMPLE.replace("\n", "\r\n"), encoding="utf-8", newline="")
        config = ConfigFile(path)
        config.set("notify", "mention", "<@1>")
        config.save()
        assert b"\r\n" in path.read_bytes()


class TestGet:
    def test_get_returns_the_raw_value(self, tmp_path):
        assert ConfigFile(written(tmp_path)).get("capture", "poll_interval_seconds") == "30"

    def test_get_is_none_for_a_missing_key(self, tmp_path):
        assert ConfigFile(written(tmp_path)).get("capture", "nothing") is None


class TestVault:
    def test_protected_marks_the_stored_form(self):
        stored = protected("https://discord.com/api/webhooks/1/secret")
        assert stored.startswith(PREFIX)

    def test_protected_round_trips(self):
        secret = "https://discord.com/api/webhooks/1/secret"
        assert revealed(protected(secret)) == secret

    def test_protecting_twice_changes_nothing(self):
        once = protected("https://discord.com/api/webhooks/1/secret")
        assert protected(once) == once

    def test_plaintext_passes_through_unchanged(self):
        assert revealed("https://discord.com/api/webhooks/1/secret").startswith("https://")

    def test_an_empty_secret_stays_empty(self):
        assert protected("") == ""
        assert revealed("") == ""

    def test_masked_never_shows_the_secret(self):
        secret = "https://discord.com/api/webhooks/1/SuperSecretToken"
        assert "SuperSecret" not in masked(secret)
        assert masked(protected(secret)) == "(encrypted)"
        assert masked("") == "(not set)"

    def test_settings_decrypt_on_load(self, tmp_path):
        from bdo_autoroute.settings import Settings

        secret = "https://discord.com/api/webhooks/1/secret"
        path = tmp_path / "config.toml"
        path.write_text(
            f'[notify]\ndiscord_webhook_url = "{protected(secret)}"\n', encoding="utf-8"
        )
        assert Settings.load(path).webhook_url == secret
