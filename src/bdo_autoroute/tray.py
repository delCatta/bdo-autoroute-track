"""A system tray icon that runs the monitor in the background.

The monitor keeps polling in a worker thread while the icon sits in the
notification area. Its tooltip carries the latest state, so a glance at the tray
answers "is it still watching?" without opening anything.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path

from PIL import Image

from .monitor import Monitor
from .voyage import Status, duration

log = logging.getLogger(__name__)

TITLE = "BDO Autoroute Track"
FALLBACK_ICON_SIZE = 64


class Tray:
    """The monitor, wrapped in a tray icon.

    Signals are the main thread's business, so the monitor is asked not to
    install a handler and is stopped through halt() from the menu instead.
    """

    def __init__(self, monitor: Monitor, *, icon: Path | None = None, logs: Path | None = None):
        try:
            import pystray
        except ImportError as exc:
            raise RuntimeError(
                "pystray is not installed, so the tray is unavailable. "
                "Run setup.cmd again, or use run.cmd instead."
            ) from exc

        self._pystray = pystray
        self._monitor = monitor
        self._logs = logs
        self._state = "starting up"
        self._worker: threading.Thread | None = None
        self._icon = pystray.Icon(
            "bdo_autoroute",
            self._image(icon),
            TITLE,
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: self._state, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Mute notifications",
                    self._toggle_mute,
                    checked=lambda _item: self._monitor.outbox.muted,
                ),
                pystray.MenuItem(
                    "Pause watching",
                    self._toggle_pause,
                    checked=lambda _item: self._monitor.paused,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open logs folder", self._open_logs),
                pystray.MenuItem("Quit", self._quit),
            ),
        )
        monitor.watch(self._remember)

    def run(self) -> int:
        """Block on the tray icon while the monitor polls behind it."""
        self._worker = threading.Thread(
            target=self._monitor.run, kwargs={"handle_signals": False}, daemon=True
        )
        self._worker.start()
        log.info("Tray running. Right-click the icon to quit.")
        self._icon.run()
        return 0

    def _remember(self, status: Status) -> None:
        """Keep the tooltip current. Called after every poll."""
        distance = f"{status.distance_m:.0f}m" if status.distance_m is not None else "unknown"
        self._state = f"{status.state.value} - {distance}"
        if status.stalled_seconds >= 1:
            self._state += f", stalled {duration(status.stalled_seconds)}"
        if self._monitor.outbox.muted:
            self._state += " (muted)"
        self._refresh()

    def _refresh(self) -> None:
        """Push the current state into the tooltip and the menu."""
        try:
            self._icon.title = f"{TITLE}\n{self._state}"
            self._icon.update_menu()
        except Exception as exc:
            log.debug("Could not refresh the tray: %s", exc)

    def _toggle_mute(self, _icon=None, _item=None) -> None:
        """Stop delivering alerts, while carrying on watching.

        Muting is deliberate silence, so it must never be mistaken for a broken
        channel - the Outbox returns early rather than recording a failure.
        """
        outbox = self._monitor.outbox
        outbox.muted = not outbox.muted
        log.info("Notifications %s.", "muted" if outbox.muted else "unmuted")
        self._refresh()

    def _toggle_pause(self, _icon=None, _item=None) -> None:
        """Stop polling entirely. Nothing is read, so nothing is missed either."""
        self._monitor.paused = not self._monitor.paused
        log.info("Watching %s.", "paused" if self._monitor.paused else "resumed")
        if self._monitor.paused:
            self._state = "paused"
        self._refresh()

    def _open_logs(self, _icon=None, _item=None) -> None:
        if self._logs is None:
            return
        self._logs.mkdir(parents=True, exist_ok=True)
        webbrowser.open(self._logs.as_uri())

    def _quit(self, _icon=None, _item=None) -> None:
        log.info("Quitting from the tray.")
        self._monitor.halt()
        if self._worker is not None:
            self._worker.join(timeout=10)
        self._icon.stop()

    @staticmethod
    def _image(icon: Path | None) -> Image.Image:
        if icon is not None and icon.exists():
            try:
                return Image.open(icon)
            except Exception as exc:
                log.debug("Could not load %s: %s", icon, exc)
        return Image.new("RGB", (FALLBACK_ICON_SIZE, FALLBACK_ICON_SIZE), (24, 28, 38))
