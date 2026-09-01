"""Stopping has to be immediate, because a person is waiting for it.

Quit on the tray menu did nothing visible for ten seconds. The loop slept
`poll_interval_seconds` between polls with `time.sleep`, which cannot be
interrupted, so `halt()` only set a flag that nothing would read until the
sleep ended. The tray then joined the worker for ten seconds from pystray's own
thread, which is the thread that draws the menu, and only stopped the icon after
giving up.

So the sequence was: click Quit, menu closes, nothing happens for ten seconds,
icon finally disappears, worker abandoned mid-sleep. It read as a broken button.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from bdo_autoroute.marker import Offset
from bdo_autoroute.monitor import Monitor
from bdo_autoroute.outbox import Outbox
from bdo_autoroute.settings import Calibration, Settings
from bdo_autoroute.voyage import Voyage

# Long enough that an uninterruptible sleep would fail these outright.
POLL_SECONDS = 30
PROMPT_SECONDS = 2.0


def monitor(**overrides) -> Monitor:
    return Monitor(
        Settings(poll_interval_seconds=POLL_SECONDS, **overrides),
        Calibration(Offset(-86, 0, 83, 14), 3440, 1440, "icon_template.png"),
        readout=None,
        outbox=Outbox([]),
        voyage=Voyage(
            arrival_threshold_m=70.0,
            movement_epsilon_m=15.0,
            stuck_after_seconds=180,
            missing_confirm_polls=4,
            near_arrival_m=400.0,
        ),
        samples_dir=Path(tempfile.mkdtemp()),
    )


class TestHalt:
    def test_halt_is_visible_at_once(self):
        watcher = monitor()
        assert not watcher.stopping
        watcher.halt()
        assert watcher.stopping

    def test_halt_returns_without_waiting(self):
        """It is called from the thread that draws the menu."""
        watcher = monitor()
        began = time.monotonic()
        watcher.halt()
        assert time.monotonic() - began < 0.1

    def test_halt_cuts_the_wait_between_polls_short(self):
        """The bug. A `time.sleep` here ignored the flag for up to 30 seconds."""
        watcher = monitor()
        threading.Timer(0.05, watcher.halt).start()

        began = time.monotonic()
        watcher._stop.wait(POLL_SECONDS)
        waited = time.monotonic() - began

        assert waited < PROMPT_SECONDS, f"waited {waited:.1f}s for a stop"

    def test_the_wait_still_runs_its_full_term_when_nothing_stops_it(self):
        watcher = monitor()
        began = time.monotonic()
        watcher._stop.wait(0.2)
        assert time.monotonic() - began >= 0.2

    def test_halting_twice_is_harmless(self):
        watcher = monitor()
        watcher.halt()
        watcher.halt()
        assert watcher.stopping
