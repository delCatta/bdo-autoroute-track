"""What every window here shares: the palette, the type, and a way home.

Dark by design. The game is dark, Discord is dark, and a white dialog popping
over either is a flashbang. The colours are close to Discord's so the window
looks like it belongs next to the one the alerts land in.
"""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable
from pathlib import Path

from .settings import ASSETS

log = logging.getLogger(__name__)

WINDOW = "#1e1f22"
CARD = "#2b2d31"
FIELD = "#383a40"
FIELD_BORDER = "#1e1f22"
TEXT = "#f2f3f5"
MUTED = "#949ba4"
ACCENT = "#5865f2"
ACCENT_HOVER = "#4752c4"
QUIET = "#4e5058"
QUIET_HOVER = "#6d6f78"
DANGER = "#f23f43"
GOOD = "#23a559"
WARNING = "#f0b232"

FAMILY = "Segoe UI"
WINDOW_ICON = ASSETS / "boat.ico"
LOGO = ASSETS / "icon.png"

# Every poll arrives on the monitor's thread; every widget belongs to the main
# one. Tk is not thread-safe, so posted work is drained this often.
DRAIN_MS = 100


def dark() -> None:
    """Set the appearance once, before any window is made."""
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")


def font(size: int = 13, *, weight: str = "normal"):
    import customtkinter as ctk

    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def brand(window, *, icon: Path = WINDOW_ICON) -> None:
    """Put the boat on the title bar.

    Twice, because customtkinter puts its own icon back about 200ms after a
    window opens. Setting it once looked right for a blink.
    """
    if not icon.exists():
        return

    def apply() -> None:
        try:
            window.iconbitmap(str(icon))
        except Exception as exc:
            log.debug("Could not set the window icon: %s", exc)

    apply()
    window.after(300, apply)


class Mailbox:
    """Work posted from any thread, run on the one that owns the widgets."""

    def __init__(self, window) -> None:
        self._window = window
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._closed = False
        self._window.after(DRAIN_MS, self._drain)

    def post(self, work: Callable[[], None]) -> None:
        self._queue.put(work)

    def close(self) -> None:
        self._closed = True

    def _drain(self) -> None:
        if self._closed:
            return
        while True:
            try:
                work = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                work()
            except Exception as exc:
                log.exception("Posted work failed: %s", exc)
        try:
            self._window.after(DRAIN_MS, self._drain)
        except Exception:
            self._closed = True
