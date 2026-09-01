"""A settings window, so nobody has to hand-edit TOML to get started.

Only the settings people actually change are here. Everything else stays in
config.toml with its explanation attached, and "Open config file" is one click
away for the rest.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .configfile import ConfigFile
from .settings import CONFIG, EXAMPLE_CONFIG, SCREENSHOT_MODES, WEBHOOK_PREFIX, Settings
from .vault import available, protected, scrubbed

log = logging.getLogger(__name__)

# What each notification mode is called in the dialog, and back again. The
# config stores the short word; nobody should have to guess what "verbose" does.
MODE_LABELS = {"verbose": "Everything", "important": "Important only"}
MODE_VALUES = {label: mode for mode, label in MODE_LABELS.items()}

SCREENSHOT_EXPLAINED = {
    "full": "Full window, includes chat and your character name",
    "marker": "Just the marker, no chat, safe for shared servers",
    "none": "Text only",
}


def ensure_config(path: Path = CONFIG) -> Path:
    """A config to edit, copied from the example the first time."""
    if not path.exists() and EXAMPLE_CONFIG.exists():
        path.write_text(EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def open_in_editor(path: Path) -> None:
    """Open the config in whatever the user has associated with .toml.

    Not `Popen(["notepad.exe", ...])`. CreateProcess searches the working
    directory first, and every `.ps1` here sets that to the repo root, so a
    notepad.exe dropped in the project folder would have won.
    """
    ensure_config(path)
    try:
        os.startfile(str(path))
    except Exception as exc:
        log.warning("Could not open %s: %s", path, exc)


class SettingsWindow:
    """The handful of settings worth a dialog."""

    def __init__(
        self,
        path: Path = CONFIG,
        *,
        parent: tk.Misc | None = None,
    ) -> None:
        self._path = ensure_config(path)
        self._config = ConfigFile(self._path)
        self._saved = False

        self._root = tk.Toplevel(parent) if parent else tk.Tk()
        self._root.title("BDO Autoroute Track - settings")
        self._root.resizable(False, False)

        current = self._current()
        self._webhook = tk.StringVar(value=current.webhook_url)
        self._mention = tk.StringVar(value=current.mention)
        self._to_discord = tk.BooleanVar(value="discord" in current.channels)
        self._to_desktop = tk.BooleanVar(value="desktop" in current.channels)
        self._discord_mode = tk.StringVar(value=MODE_LABELS[current.discord_mode])
        self._desktop_mode = tk.StringVar(value=MODE_LABELS[current.desktop_mode])
        self._screenshot = tk.StringVar(value=current.screenshot)
        self._poll = tk.StringVar(value=str(current.poll_interval_seconds))
        self._arrival = tk.StringVar(value=str(int(current.arrival_threshold_m)))
        self._stuck = tk.StringVar(value=str(int(current.stuck_after_seconds)))
        self._logging = tk.BooleanVar(value=current.log_to_file)

        self._build()

    def show(self) -> bool:
        """Run the dialog. True if the settings were saved."""
        self._root.mainloop()
        return self._saved

    def _current(self) -> Settings:
        try:
            return Settings.load(self._path)
        except Exception as exc:
            log.warning("Could not read %s (%s); showing defaults.", self._path, exc)
            return Settings()

    # -- layout ----------------------------------------------------------

    def _build(self) -> None:
        frame = ttk.Frame(self._root, padding=14)
        frame.grid(sticky="nsew")
        row = 0

        ttk.Label(frame, text="Where alerts go", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        for label, enabled, mode, hint in (
            ("Discord", self._to_discord, self._discord_mode, "a phone alert is cheap to ignore"),
            (
                "Windows notification",
                self._to_desktop,
                self._desktop_mode,
                "a toast every minute teaches you to dismiss them",
            ),
        ):
            ttk.Checkbutton(frame, text=label, variable=enabled).grid(
                row=row, column=0, sticky="w"
            )
            ttk.Combobox(
                frame,
                textvariable=mode,
                values=list(MODE_LABELS.values()),
                state="readonly",
                width=16,
            ).grid(row=row, column=1, sticky="w")
            ttk.Label(frame, text=hint, foreground="#666").grid(
                row=row, column=2, sticky="w"
            )
            row += 1

        ttk.Label(
            frame,
            text="Important only skips the heartbeat and sends what needs you.",
            foreground="#666",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 0))
        row += 1

        ttk.Label(frame, text="Webhook URL").grid(row=row, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self._webhook, width=52).grid(
            row=row, column=1, sticky="we", pady=(10, 0)
        )
        ttk.Button(frame, text="Test", command=self._test).grid(
            row=row, column=2, sticky="w", padx=(6, 0), pady=(10, 0)
        )
        row += 1
        ttk.Label(
            frame,
            text="Discord: Edit Channel > Integrations > Webhooks > New Webhook > Copy URL",
            foreground="#666",
        ).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1

        ttk.Label(frame, text="Mention").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self._mention, width=52).grid(
            row=row, column=1, columnspan=2, sticky="we", pady=(8, 0)
        )
        row += 1
        ttk.Label(
            frame,
            text="<@your-user-id> so alerts buzz your phone. Leave blank for silent.",
            foreground="#666",
        ).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="we", pady=12
        )
        row += 1

        ttk.Label(frame, text="Screenshot", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        for mode in SCREENSHOT_MODES:
            ttk.Radiobutton(
                frame,
                text=SCREENSHOT_EXPLAINED[mode],
                value=mode,
                variable=self._screenshot,
            ).grid(row=row, column=0, columnspan=3, sticky="w")
            row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="we", pady=12
        )
        row += 1

        for label, variable, hint in (
            ("Check every (seconds)", self._poll, "30 is a good default"),
            ("Arrived under (metres)", self._arrival, "70, it rarely reaches 0"),
            ("Stuck after (seconds)", self._stuck, "180 before it calls it stuck"),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(frame, textvariable=variable, width=8).grid(row=row, column=1, sticky="w")
            ttk.Label(frame, text=hint, foreground="#666").grid(row=row, column=2, sticky="w")
            row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="we", pady=12
        )
        row += 1
        ttk.Checkbutton(
            frame, text="Write a log file", variable=self._logging
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame, text="logs/autoroute.log, turn on to chase a misread", foreground="#666"
        ).grid(row=row, column=2, sticky="w")
        row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Open config file", command=self._open_file).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(buttons, text="Cancel", command=self._root.destroy).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(buttons, text="Save", command=self._save).pack(side="left")

    # -- actions ---------------------------------------------------------

    def _channels(self) -> list[str]:
        chosen = []
        if self._to_discord.get():
            chosen.append("discord")
        if self._to_desktop.get():
            chosen.append("desktop")
        return chosen

    def _complaint(self) -> str | None:
        """Whatever is wrong with what has been typed, in one sentence."""
        if not self._channels():
            return "Pick at least one place for alerts to go."

        webhook = self._webhook.get().strip()
        if "discord" in self._channels():
            if not webhook:
                return "Discord needs a webhook URL, or untick Discord."
            if not webhook.startswith(WEBHOOK_PREFIX):
                return f"That does not look like a webhook URL.\nThey start with {WEBHOOK_PREFIX}"

        for label, variable in (
            ("Check every", self._poll),
            ("Arrived under", self._arrival),
            ("Stuck after", self._stuck),
        ):
            try:
                if int(variable.get()) < 1:
                    return f"{label} must be a positive whole number."
            except ValueError:
                return f"{label} must be a whole number."
        return None

    def _test(self) -> None:
        from .alerts import Alert
        from .discord import Discord

        webhook = self._webhook.get().strip()
        if not webhook.startswith(WEBHOOK_PREFIX):
            messagebox.showwarning(
                "Test", f"That does not look like a webhook URL.\nThey start with {WEBHOOK_PREFIX}"
            )
            return
        try:
            sent = Discord(webhook, self._mention.get().strip()).deliver(Alert.test_message())
        except Exception as exc:
            messagebox.showerror("Test", f"Could not send. {scrubbed(str(exc), webhook)}")
            return

        if sent:
            messagebox.showinfo("Test", "Sent. Check your Discord channel.")
        else:
            messagebox.showerror("Test", "Discord rejected it. Is the URL still valid?")

    def _open_file(self) -> None:
        open_in_editor(self._path)

    def _save(self) -> None:
        complaint = self._complaint()
        if complaint:
            messagebox.showwarning("Settings", complaint)
            return

        self._config.set("notify", "channels", self._channels())
        self._config.set(
            "notify", "discord_webhook_url", protected(self._webhook.get().strip())
        )
        self._config.set("notify", "mention", self._mention.get().strip())
        self._config.set("notify", "discord_mode", MODE_VALUES[self._discord_mode.get()])
        self._config.set("notify", "desktop_mode", MODE_VALUES[self._desktop_mode.get()])
        self._config.set("notify", "screenshot", self._screenshot.get())
        self._config.set("capture", "poll_interval_seconds", int(self._poll.get()))
        self._config.set("detect", "arrival_threshold_m", float(self._arrival.get()))
        self._config.set("detect", "stuck_after_seconds", int(self._stuck.get()))
        self._config.set("logging", "to_file", bool(self._logging.get()))
        self._config.save()

        self._saved = True
        log.info("Settings saved to %s", self._path)
        stored = "encrypted for this Windows account" if available() else "stored as plain text"
        messagebox.showinfo("Settings", f"Saved. The webhook is {stored}.")
        self._root.destroy()
