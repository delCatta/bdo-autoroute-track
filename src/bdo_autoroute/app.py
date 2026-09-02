"""The window. What a double-click on the exe opens.

It has two faces. Before set-up is complete it is a checklist of the two
things left to do, and each has a button. After that it is the same status the
tray tooltip carries, large enough to read from the sofa, with the switches
the tray menu has. Closing it hides it. The tray icon keeps watching, and a
double-click on the icon brings the window back.

Tk owns the main thread here, so the tray runs detached and the monitor polls
on a worker. Everything either of them wants to show goes through the mailbox.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PIL import Image

from . import __version__, ui
from .alerts import COLOURS
from .commands import LOGS, build_monitor, build_outbox, calibration_frame, fit_calibration
from .configure import SettingsWindow, ensure_config
from .marker import MarkerError
from .monitor import Monitor
from .picker import digits_and_icon
from .settings import APP_NAME, CALIBRATION, CONFIG, ICON, Settings, SettingsError
from .tray import Facts, Tray
from .voyage import State, Status
from .window import CaptureError

log = logging.getLogger(__name__)

CALIBRATE_HINT = "Black Desert running, on an auto-route, with the marker on screen."
ALERTS_HINT = "Discord, a Windows notification, or both."


class Checklist:
    """What still stands between a fresh install and watching a route.

    Two things, and it says which. Kept apart from the window so the answer
    can be tested without a desktop.
    """

    def __init__(
        self, *, config: Path = CONFIG, calibration: Path = CALIBRATION, icon: Path = ICON
    ) -> None:
        self._config = config
        self._calibration = calibration
        self._icon = icon

    @property
    def settings(self) -> Settings | None:
        try:
            return Settings.load(self._config)
        except Exception as exc:
            log.debug("Config not usable yet: %s", exc)
            return None

    @property
    def reachable(self) -> bool:
        """Somewhere an alert could actually go."""
        settings = self.settings
        if settings is None:
            return False
        if "desktop" in settings.channels:
            return True
        return "discord" in settings.channels and bool(settings.webhook_url)

    @property
    def calibrated(self) -> bool:
        return self._calibration.exists() and self._icon.exists()

    @property
    def ready(self) -> bool:
        return self.reachable and self.calibrated

    @property
    def next_step(self) -> str:
        if not self.reachable:
            return "Choose where alerts go."
        if not self.calibrated:
            return "Show it the marker."
        return "Ready."


class App:
    """The window, the tray under it, and the monitor behind both."""

    def __init__(self, *, hidden: bool = False) -> None:
        import customtkinter as ctk

        ui.dark()
        ensure_config()
        self._ctk = ctk
        self._facts = Facts()
        self._monitor: Monitor | None = None
        self._worker: threading.Thread | None = None
        self._tray: Tray | None = None
        self._closing = False

        self._root = ctk.CTk(fg_color=ui.WINDOW)
        self._root.title(APP_NAME)
        self._root.geometry("480x540")
        self._root.minsize(440, 500)
        ui.brand(self._root)
        self._mailbox = ui.Mailbox(self._root)

        self._build()
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        if hidden:
            self._root.withdraw()
        self._root.after(50, self._settle)

    def run(self) -> int:
        self._root.mainloop()
        return 0

    # -- layout ----------------------------------------------------------

    def _build(self) -> None:
        ctk = self._ctk
        body = ctk.CTkFrame(self._root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(18, 16))

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))
        if ui.LOGO.exists():
            self._logo = ctk.CTkImage(light_image=Image.open(ui.LOGO), size=(40, 40))
            ctk.CTkLabel(header, image=self._logo, text="").pack(side="left", padx=(0, 12))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=APP_NAME, font=ui.font(18, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            titles, text=f"v{__version__}", font=ui.font(11), text_color=ui.MUTED
        ).pack(anchor="w")

        self._setup = self._setup_card(body)
        self._status = self._status_card(body)

        self._notice = ctk.CTkLabel(
            body, text="", font=ui.font(12), text_color=ui.MUTED, wraplength=420, justify="left"
        )
        self._notice.pack(anchor="w", pady=(12, 0))

        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        self._quiet(footer, "Settings", self._open_settings, width=96).pack(side="left")
        self._quiet(footer, "Calibrate", self._calibrate, width=96).pack(side="left", padx=(8, 0))
        self._quiet(footer, "Report", self._report, width=80).pack(side="left", padx=(8, 0))
        self._quiet(footer, "Logs", self._open_logs, width=64).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            footer,
            text="Quit",
            command=self._quit,
            width=60,
            height=34,
            font=ui.font(),
            fg_color="transparent",
            hover_color=ui.CARD,
            text_color=ui.MUTED,
        ).pack(side="right")

    def _card(self, parent):
        card = self._ctk.CTkFrame(parent, fg_color=ui.CARD, corner_radius=12)
        inner = self._ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=16)
        return card, inner

    def _setup_card(self, parent):
        ctk = self._ctk
        card, inner = self._card(parent)
        ctk.CTkLabel(inner, text="Two steps before it can watch.", font=ui.font(16, weight="bold")).pack(
            anchor="w", pady=(0, 10)
        )
        self._alerts_step = self._step(inner, "Choose where alerts go", ALERTS_HINT, "Settings", self._open_settings)
        self._marker_step = self._step(inner, "Show it the marker", CALIBRATE_HINT, "Calibrate", self._calibrate)
        return card

    def _step(self, parent, title: str, hint: str, action: str, command):
        ctk = self._ctk
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)
        dot = ctk.CTkLabel(row, text="●", font=ui.font(16), text_color=ui.MUTED, width=20)
        dot.pack(side="left", anchor="n")
        words = ctk.CTkFrame(row, fg_color="transparent")
        words.pack(side="left", fill="x", expand=True, padx=(6, 8))
        ctk.CTkLabel(words, text=title, font=ui.font(14, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            words, text=hint, font=ui.font(12), text_color=ui.MUTED, wraplength=250, justify="left"
        ).pack(anchor="w")
        self._accent(row, action, command).pack(side="right", anchor="n")
        return dot

    def _status_card(self, parent):
        ctk = self._ctk
        card, inner = self._card(parent)

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        self._dot = ctk.CTkLabel(top, text="●", font=ui.font(22), text_color=ui.MUTED, width=24)
        self._dot.pack(side="left", padx=(0, 8))
        self._headline = ctk.CTkLabel(top, text="Starting up", font=ui.font(24, weight="bold"))
        self._headline.pack(side="left")

        self._distance = ctk.CTkLabel(inner, text="", font=ui.font(15))
        self._distance.pack(anchor="w", pady=(8, 0))
        self._timing = ctk.CTkLabel(inner, text="", font=ui.font(13), text_color=ui.MUTED)
        self._timing.pack(anchor="w")
        self._delivery = ctk.CTkLabel(inner, text="", font=ui.font(13), text_color=ui.MUTED)
        self._delivery.pack(anchor="w")
        self._checked = ctk.CTkLabel(inner, text="", font=ui.font(11), text_color=ui.MUTED)
        self._checked.pack(anchor="w", pady=(2, 0))

        controls = ctk.CTkFrame(inner, fg_color="transparent")
        controls.pack(fill="x", pady=(16, 0))
        self._pause = self._quiet(controls, "Pause", self._toggle_pause, width=90)
        self._pause.pack(side="left")
        self._discord_switch = self._switch(controls, "Discord", "discord")
        self._desktop_switch = self._switch(controls, "Windows", "desktop")
        return card

    def _switch(self, parent, label: str, channel: str):
        switch = self._ctk.CTkSwitch(
            parent,
            text=label,
            font=ui.font(),
            progress_color=ui.ACCENT,
            command=lambda: self._toggle_channel(channel),
        )
        switch.pack(side="right", padx=(12, 0))
        return switch

    def _quiet(self, parent, text: str, command, *, width: int = 110):
        return self._ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=34,
            font=ui.font(),
            fg_color=ui.QUIET,
            hover_color=ui.QUIET_HOVER,
            corner_radius=6,
        )

    def _accent(self, parent, text: str, command, *, width: int = 100):
        return self._ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=34,
            font=ui.font(weight="bold"),
            fg_color=ui.ACCENT,
            hover_color=ui.ACCENT_HOVER,
            corner_radius=6,
        )

    # -- which face to show -----------------------------------------------

    def _settle(self) -> None:
        """Show the checklist or the status, and start watching if it can."""
        checklist = Checklist()
        if checklist.ready:
            self._setup.pack_forget()
            self._status.pack(fill="x")
            if self._monitor is None:
                self._start()
            return

        self._status.pack_forget()
        self._setup.pack(fill="x")
        self._alerts_step.configure(text_color=ui.GOOD if checklist.reachable else ui.MUTED)
        self._marker_step.configure(text_color=ui.GOOD if checklist.calibrated else ui.MUTED)

    def _say(self, text: str, colour: str = ui.MUTED) -> None:
        self._notice.configure(text=text, text_color=colour)

    def _show(self) -> None:
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    # -- the monitor ------------------------------------------------------

    def _start(self) -> None:
        try:
            settings = Settings.load()
            monitor = build_monitor(settings)
        except (SettingsError, CaptureError, MarkerError) as exc:
            self._say(str(exc), ui.DANGER)
            return
        except Exception as exc:
            log.exception("Could not start watching: %s", exc)
            self._say(f"Could not start watching. {exc}", ui.DANGER)
            return

        self._monitor = monitor
        monitor.watch(lambda status: self._mailbox.post(lambda: self._took(status)))
        self._tray = Tray(
            monitor,
            logs=LOGS,
            on_open=lambda: self._mailbox.post(self._show),
            on_settings=lambda: self._mailbox.post(self._open_settings),
            on_quit=lambda: self._mailbox.post(self._leave),
        )
        self._tray.start()
        self._worker = threading.Thread(target=self._watch, args=(monitor,), daemon=True)
        self._worker.start()
        self._say("Watching. Closing this window keeps it running in the tray.")

    def _watch(self, monitor: Monitor) -> None:
        """The worker. Anything that ends the loop early is said in the window."""
        try:
            monitor.run(handle_signals=False)
        except Exception as exc:
            log.exception("Watching stopped: %s", exc)
            self._mailbox.post(lambda: self._say(f"Stopped. {exc}", ui.DANGER))

    def _stop(self) -> None:
        if self._monitor is not None:
            self._monitor.halt()
        if self._tray is not None:
            self._tray.stop()
        if self._worker is not None:
            self._worker.join(timeout=5)
        self._monitor = None
        self._tray = None
        self._worker = None

    def _took(self, status: Status) -> None:
        """One poll, into the window."""
        if self._monitor is None:
            return
        outbox = self._monitor.outbox
        self._facts.update(
            status,
            channels=outbox.speaking,
            muted=outbox.muted,
            paused=self._monitor.paused,
        )
        self._refresh()

    def _refresh(self) -> None:
        facts = self._facts
        state = State.STARTING if facts.paused else facts.state
        self._dot.configure(text_color=f"#{COLOURS[state]:06x}")
        self._headline.configure(text=facts.headline)
        self._distance.configure(text=facts.distance)
        self._timing.configure(text=facts.timing)
        self._delivery.configure(text=facts.delivery)
        self._checked.configure(
            text=f"Checked {facts.seen_at:%H:%M:%S}" if facts.seen_at else "Starting up"
        )
        self._pause.configure(text="Resume" if facts.paused else "Pause")
        if self._monitor is not None:
            outbox = self._monitor.outbox
            for switch, channel in ((self._discord_switch, "discord"), (self._desktop_switch, "desktop")):
                if not outbox.has(channel):
                    switch.pack_forget()
                    continue
                switch.pack(side="right", padx=(12, 0))
                if outbox.silenced(channel):
                    switch.deselect()
                else:
                    switch.select()

    # -- controls ---------------------------------------------------------

    def _toggle_pause(self) -> None:
        if self._monitor is None:
            return
        self._monitor.paused = not self._monitor.paused
        log.info("Watching %s.", "paused" if self._monitor.paused else "resumed")
        self._facts.paused = self._monitor.paused
        self._refresh()
        if self._tray is not None:
            self._tray.sync()

    def _toggle_channel(self, channel: str) -> None:
        if self._monitor is None:
            return
        outbox = self._monitor.outbox
        quiet = not outbox.silenced(channel)
        outbox.silence(channel, quiet)
        log.info("%s alerts %s.", channel, "off" if quiet else "on")
        self._facts.channels = outbox.speaking
        self._facts.muted = outbox.muted
        self._refresh()
        if self._tray is not None:
            self._tray.sync()

    def _open_settings(self) -> None:
        self._show()
        dialog = SettingsWindow(parent=self._root)
        if not dialog.show():
            return
        self._say(dialog.outcome, ui.GOOD)
        if self._monitor is None:
            self._settle()
            return
        try:
            settings = Settings.load()
        except Exception as exc:
            self._say(f"Saved settings could not be loaded. {exc}", ui.DANGER)
            return
        self._monitor.apply(settings, build_outbox(settings))
        self._facts.channels = self._monitor.outbox.speaking
        self._facts.muted = self._monitor.outbox.muted
        self._refresh()
        if self._tray is not None:
            self._tray.sync()

    def _calibrate(self) -> None:
        """Box the digits and the icon, then start over on the new calibration."""
        try:
            settings = Settings.load()
            frame, window = calibration_frame(settings)
        except (SettingsError, CaptureError) as exc:
            self._say(str(exc), ui.WARNING)
            return
        except Exception as exc:
            log.exception("Could not capture the game: %s", exc)
            self._say(f"Could not capture the game. {exc}", ui.DANGER)
            return

        boxes = digits_and_icon(frame, parent=self._root)
        if boxes is None:
            self._say("Calibration cancelled. Nothing was changed.")
            return

        try:
            fit = fit_calibration(settings, frame, *boxes, window.size)
        except MarkerError as exc:
            self._say(str(exc), ui.WARNING)
            return
        self._say(fit.summary, ui.GOOD if fit.ok else ui.WARNING)

        if self._monitor is not None:
            self._stop()
        self._settle()

    def _open_logs(self) -> None:
        import webbrowser

        LOGS.mkdir(parents=True, exist_ok=True)
        webbrowser.open(LOGS.as_uri())

    def _report(self) -> None:
        """Build the report that is safe to attach to an issue, and show where it is.

        The same thing `scrub.cmd` does from a checkout. Someone who installed
        the exe has no terminal to run that from, and CONTRIBUTING asks for
        this zip rather than raw files for a reason.
        """
        import webbrowser

        from .bundle import Bundle
        from .settings import ROOT

        try:
            settings = Settings.load()
            target = Bundle(ROOT, settings).write()
        except Exception as exc:
            log.exception("Could not build the report: %s", exc)
            self._say(f"Could not build the report. {exc}", ui.DANGER)
            return
        self._say(
            f"Report written to {target.name}. It holds the log with every webhook "
            "token removed, the digit crops and your calibration, and nothing "
            "else. Open it and look before attaching it to an issue.",
            ui.GOOD,
        )
        webbrowser.open(target.parent.as_uri())

    # -- leaving ----------------------------------------------------------

    def _close(self) -> None:
        """The close button hides the window while there is a tray to go to."""
        if self._tray is None:
            self._quit()
            return
        self._root.withdraw()
        log.info("Window hidden. Still watching from the tray.")

    def _quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop()
        self._leave()

    def _leave(self) -> None:
        """Take the window down. The tray has already gone by the time it calls this."""
        self._closing = True
        self._mailbox.close()
        try:
            self._root.destroy()
        except Exception as exc:
            log.debug("Window already gone: %s", exc)
