"""Regressions from a security review, 2026-09-01.

The one that mattered: a Discord webhook URL is a bearer credential, and
`requests` puts the URL it was given into its exception messages. Logging one
raw wrote the live token into logs/autoroute.log, which is exactly the file
CONTRIBUTING.md asks people to attach to a GitHub issue. All the DPAPI work in
vault.py was defeated at the one moment it was supposed to matter.

Both exception shapes are covered here, because they leak differently. An HTTP
error carries the whole URL; a connection error carries only the path.
"""

from __future__ import annotations

import tomllib

import pytest
import requests

from bdo_autoroute.configfile import as_toml
from bdo_autoroute.discord import Discord
from bdo_autoroute.settings import WEBHOOK_PREFIX, Settings, SettingsError
from bdo_autoroute.vault import scrubbed

# Shaped like a real webhook (19-digit id, 68-character token) and entirely
# made up. Never put a live credential in a fixture.
TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
WEBHOOK = f"{WEBHOOK_PREFIX}1111111111111111111/{TOKEN}"


class TestScrubbed:
    def test_scrubbed_removes_a_token_from_a_full_url(self):
        assert TOKEN not in scrubbed(f"401 Client Error for url: {WEBHOOK}")

    def test_scrubbed_removes_a_token_from_a_bare_path(self):
        """A connection error names the path only, with the host elsewhere."""
        message = f"Max retries exceeded with url: /api/webhooks/1111111111111111111/{TOKEN}"
        assert TOKEN not in scrubbed(message)

    def test_scrubbed_keeps_the_rest_of_the_message(self):
        cleaned = scrubbed(f"401 Client Error: Unauthorized for url: {WEBHOOK}")
        assert "401" in cleaned and "Unauthorized" in cleaned

    def test_scrubbed_masks_a_secret_it_is_given(self):
        assert TOKEN not in scrubbed(f"failed for {WEBHOOK}", WEBHOOK)

    def test_scrubbed_leaves_ordinary_text_alone(self):
        assert scrubbed("nothing secret here") == "nothing secret here"


class TestDiscordLogging:
    def discord(self) -> Discord:
        return Discord(WEBHOOK)

    def test_an_http_error_does_not_carry_the_token(self):
        response = requests.Response()
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = WEBHOOK
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            assert TOKEN not in self.discord()._safely(exc)
        else:
            pytest.fail("raise_for_status did not raise")

    def test_a_connection_error_does_not_carry_the_token(self):
        exc = requests.ConnectionError(
            "HTTPSConnectionPool(host='discord.com', port=443): Max retries "
            f"exceeded with url: /api/webhooks/1111111111111111111/{TOKEN}"
        )
        assert TOKEN not in self.discord()._safely(exc)

    def test_the_message_still_names_what_went_wrong(self):
        exc = requests.ConnectTimeout("timed out")
        assert "ConnectTimeout" in self.discord()._safely(exc)


class TestWebhookHost:
    def loaded(self, url: str, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(f'[notify]\ndiscord_webhook_url = "{url}"\n', encoding="utf-8")
        return Settings.load(path)

    def test_another_host_is_refused_on_the_config_path(self, tmp_path):
        """Hot reload means config.toml is trusted at runtime, not just at start.

        Anything able to write it could otherwise redirect full-window
        screenshots to an arbitrary host with no restart and no prompt.
        """
        with pytest.raises(SettingsError, match="discord_webhook_url"):
            self.loaded("https://evil.example/api/webhooks/1/x", tmp_path)

    def test_a_real_webhook_is_accepted(self, tmp_path):
        assert self.loaded(WEBHOOK, tmp_path).webhook_url == WEBHOOK

    def test_an_empty_webhook_is_fine(self, tmp_path):
        """Desktop-only setups leave it blank, and that must keep working."""
        assert self.loaded("", tmp_path).webhook_url == ""


class TestTomlEscaping:
    """No backslash inside an f-string expression in this file.

    That is a 3.12 feature, and this project supports 3.11. The first version
    of these tests used one, so the file did not parse on the older runner at
    all, and CI caught what a 3.12 development machine could not.
    """

    def round_trip(self, value: str) -> str:
        return tomllib.loads("k = " + as_toml(value))["k"]

    def test_a_newline_does_not_break_the_file(self):
        assert self.round_trip("a\nb") == "a\nb"

    def test_a_carriage_return_does_not_break_the_file(self):
        assert self.round_trip("a\r\nb") == "a\r\nb"

    def test_a_tab_does_not_break_the_file(self):
        assert self.round_trip("a\tb") == "a\tb"

    def test_a_quote_still_round_trips(self):
        assert self.round_trip('say "hi"') == 'say "hi"'

    def test_a_backslash_still_round_trips(self):
        assert self.round_trip("C:\\path") == "C:\\path"

    def test_a_multiline_mention_is_written_on_one_line(self):
        """The shape that started this, a pasted value with a newline in it."""
        assert "\n" not in as_toml("<@123>\nextra")
