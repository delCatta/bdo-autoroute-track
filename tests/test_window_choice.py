"""Picking the game window when several windows answer to the same name.

Seen live. Three windows matched the title "Black Desert":

    Discord.exe        '#barter-chat | Black Desert - Sailing - Discord'
    chrome.exe         'GitHub - ... Black Desert Online ...'
    BlackDesert64.exe  'BLACK DESERT - 528853'

Windows enumerates front-to-back, and the code took the first match, so
alt-tabbing to read an alert was enough to start screenshotting Discord. The
process is the reliable identifier; the title is only a fallback.
"""

from __future__ import annotations

import pytest

from bdo_autoroute.window import Window

GAME = (1639912, "BLACK DESERT - 528853")
DISCORD = (197122, "#barter-chat | Black Desert - Sailing - Discord")
CHROME = (3280048, "GitHub - delCatta/bdo-autoroute-track: ... Black Desert Online ...")

PROCESSES = {
    GAME[0]: "BlackDesert64.exe",
    DISCORD[0]: "Discord.exe",
    CHROME[0]: "chrome.exe",
}

TITLES = ["Black Desert"]
WANTED = ["BlackDesert64.exe"]


@pytest.fixture
def named(monkeypatch):
    monkeypatch.setattr(
        "bdo_autoroute.window.process_name", lambda hwnd: PROCESSES.get(hwnd, "")
    )


def search(windows, titles=TITLES, processes=WANTED):
    return Window._search(windows, titles, processes)


class TestSearch:
    def test_search_prefers_the_game_process_over_anything_in_front(self, named):
        assert search([DISCORD, CHROME, GAME]) == GAME

    def test_search_finds_the_game_wherever_it_sits_in_z_order(self, named):
        for order in ([GAME, DISCORD, CHROME], [CHROME, GAME, DISCORD], [DISCORD, CHROME, GAME]):
            assert search(order) == GAME

    def test_search_falls_back_to_the_title_when_the_process_is_unknown(self, named):
        assert search([DISCORD, CHROME], processes=["NotRunning.exe"]) == DISCORD

    def test_search_returns_none_when_nothing_matches_at_all(self, named):
        assert search([(1, "Notepad"), (2, "Calculator")]) is None

    def test_search_ignores_titles_once_the_process_matches(self, named):
        assert search([DISCORD, GAME], titles=["nothing like this"]) == GAME

    def test_search_warns_when_several_titles_match_without_a_process(self, named, caplog):
        search([DISCORD, CHROME], processes=["NotRunning.exe"])
        assert "3 windows" not in caplog.text
        assert "2 windows" in caplog.text

    def test_search_is_quiet_when_only_one_title_matches(self, named, caplog):
        search([DISCORD], processes=["NotRunning.exe"])
        assert "windows share the title" not in caplog.text


class TestProcessMatching:
    def test_process_comparison_ignores_case(self, named):
        assert search([DISCORD, GAME], processes=["blackdesert64.EXE"]) == GAME

    def test_an_empty_process_list_leaves_only_the_title(self, named):
        assert search([DISCORD, GAME], processes=[]) == DISCORD


class TestWindowRecordsItsProcess:
    def test_process_defaults_to_empty(self):
        window = Window(
            hwnd=1,
            title="x",
            left=0,
            top=0,
            width=10,
            height=10,
            frame_left=0,
            frame_top=0,
        )
        assert window.process == ""

    def test_process_is_carried_on_the_window(self):
        window = Window(
            hwnd=1,
            title="x",
            left=0,
            top=0,
            width=10,
            height=10,
            frame_left=0,
            frame_top=0,
            process="BlackDesert64.exe",
        )
        assert window.process == "BlackDesert64.exe"
