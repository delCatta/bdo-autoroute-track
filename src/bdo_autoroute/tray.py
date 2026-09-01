"""A system tray icon that runs the monitor in the background.

The monitor keeps polling in a worker thread while the icon sits in the
notification area. Its tooltip carries the latest state, so a glance at the tray
answers "is it still watching?" without opening anything.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from PIL import Image

from .icons import every_state, for_state
from .monitor import Monitor
from .voyage import State, Status, duration

log = logging.getLogger(__name__)

TITLE = "BDO Autoroute Track"


class Facts:
    """What the tray knows, phrased for a menu that has no room to explain.

    Kept apart from the icon so the wording can be tested without a desktop.
    """

    def __init__(self) -> None:
        self.state = State.STARTING
        self.distance_m: float | None = None
        self.eta_seconds: float | None = None
        self.stalled_seconds = 0.0
        self.seen_at: datetime | None = None
        self.channels: list[str] = []
        self.muted = False
        self.paused = False

    def update(self, status: Status, *, channels: list[str], muted: bool, paused: bool) -> None:
        self.state = status.state
        self.distance_m = status.distance_m
        self.eta_seconds = status.eta_seconds
        self.stalled_seconds = status.stalled_seconds
        self.seen_at = datetime.now()
        self.channels = channels
        self.muted = muted
        self.paused = paused

    @property
    def headline(self) -> str:
        if self.paused:
            return "Paused"
        return self.state.headline

    @property
    def distance(self) -> str:
        if self.distance_m is None:
            return "Distance unknown"
        return f"{self.distance_m:.0f}m remaining"

    @property
    def timing(self) -> str:
        if self.stalled_seconds >= 1:
            return f"No progress for {duration(self.stalled_seconds)}"
        if self.eta_seconds:
            return f"About {duration(self.eta_seconds)} to go"
        return "Working out the pace"

    @property
    def delivery(self) -> str:
        if self.muted:
            return "Notifications muted"
        if not self.channels:
            return "Nowhere to send alerts"
        return "Alerting " + " and ".join(self.channels)

    @property
    def tooltip(self) -> str:
        seen = f"checked {self.seen_at:%H:%M:%S}" if self.seen_at else "starting up"
        lines = [TITLE, f"{self.headline} - {self.distance}", self.timing, seen]
        if self.muted:
            lines.append("muted")
        return "\n".join(lines)


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
        self._worker: threading.Thread | None = None
        self._icons = every_state()
        self._facts = Facts()
        self._icon = pystray.Icon(
            "bdo_autoroute",
            self._image(icon),
            TITLE,
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: self._facts.headline, None, enabled=False),
                pystray.MenuItem(lambda _item: self._facts.distance, None, enabled=False),
                pystray.MenuItem(lambda _item: self._facts.timing, None, enabled=False),
                pystray.MenuItem(lambda _item: self._facts.delivery, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Discord alerts",
                    self._toggle("discord"),
                    checked=lambda _item: not self._monitor.outbox.silenced("discord"),
                    visible=lambda _item: self._monitor.outbox.has("discord"),
                ),
                pystray.MenuItem(
                    "Windows notifications",
                    self._toggle("desktop"),
                    checked=lambda _item: not self._monitor.outbox.silenced("desktop"),
                    visible=lambda _item: self._monitor.outbox.has("desktop"),
                ),
                pystray.MenuItem(
                    "Mute everything",
                    self._toggle_mute,
                    checked=lambda _item: self._monitor.outbox.muted,
                ),
                pystray.MenuItem(
                    "Pause watching",
                    self._toggle_pause,
                    checked=lambda _item: self._monitor.paused,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Settings...", self._settings),
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
        """Take in one poll. Called after every one."""
        self._facts.update(
            status,
            channels=self._monitor.outbox.names,
            muted=self._monitor.outbox.muted,
            paused=self._monitor.paused,
        )
        self._refresh()

    def _refresh(self) -> None:
        """Push the state into the icon, the tooltip and the menu."""
        try:
            self._icon.icon = self._icon_for()
            self._icon.title = self._facts.tooltip
            self._icon.update_menu()
        except Exception as exc:
            log.debug("Could not refresh the tray: %s", exc)

    def _icon_for(self) -> Image.Image:
        """Paused looks like idle; muted greys the hull."""
        state = State.STARTING if self._monitor.paused else self._facts.state
        muted = self._monitor.outbox.muted
        return self._icons.get((state, muted)) or for_state(state, muted=muted)

    def _toggle(self, channel: str):
        """A menu action that silences or resumes one channel.

        Silencing one is not the same as a failure: the Outbox skips it without
        counting a missed delivery, so a deliberately quiet Discord never gets
        reported as broken.
        """

        def switch(_icon=None, _item=None) -> None:
            outbox = self._monitor.outbox
            quiet = not outbox.silenced(channel)
            outbox.silence(channel, quiet)
            log.info("%s alerts %s.", channel, "off" if quiet else "on")
            self._refresh()

        return switch

    def _toggle_mute(self, _icon=None, _item=None) -> None:
        """Stop delivering alerts, while carrying on watching.

        Muting is deliberate silence, so it must never be mistaken for a broken
        channel - the Outbox returns early rather than recording a failure.
        """
        outbox = self._monitor.outbox
        outbox.muted = not outbox.muted
        log.info("Notifications %s.", "muted" if outbox.muted else "unmuted")
        self._facts.muted = outbox.muted
        self._refresh()

    def _toggle_pause(self, _icon=None, _item=None) -> None:
        """Stop polling entirely. Nothing is read, so nothing is missed either."""
        self._monitor.paused = not self._monitor.paused
        log.info("Watching %s.", "paused" if self._monitor.paused else "resumed")
        self._facts.paused = self._monitor.paused
        self._refresh()

    def _settings(self, _icon=None, _item=None) -> None:
        """Open the settings window on its own thread.

        Tk insists on owning whichever thread it runs on, and this one belongs
        to pystray.
        """
        def show() -> None:
            from .configure import SettingsWindow

            try:
                if SettingsWindow().show():
                    self._reload()
            except Exception as exc:
                log.warning("Could not open settings: %s", exc)

        threading.Thread(target=show, daemon=True).start()

    def _reload(self) -> None:
        """Adopt the saved settings without restarting anything."""
        from .commands import build_outbox
        from .settings import Settings

        try:
            settings = Settings.load()
        except Exception as exc:
            log.error("Saved settings could not be loaded: %s", exc)
            return

        self._monitor.apply(settings, build_outbox(settings))
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

    def _image(self, _icon: Path | None) -> Image.Image:
        return self._icons[(State.STARTING, False)]
