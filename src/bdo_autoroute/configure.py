"""A settings window, so nobody has to hand-edit TOML to get started.

Only the settings people actually change are here. Everything else stays in
config.toml with its explanation attached, and "Open config file" is one click
away for the rest.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path

from . import ui
from .configfile import ConfigFile
from .settings import (
    CONFIG,
    EXAMPLE_CONFIG,
    Settings,
    is_webhook,
    webhook_hosts_in_words,
)
from .vault import available, protected, scrubbed

log = logging.getLogger(__name__)

# What each notification mode is called in the dialog, and back again. The
# config stores the short word; nobody should have to guess what "verbose" does.
MODE_LABELS = {"verbose": "Everything", "important": "Important only"}
MODE_VALUES = {label: mode for mode, label in MODE_LABELS.items()}

SCREENSHOT_LABELS = {"full": "Full window", "marker": "Marker only", "none": "Text only"}
SCREENSHOT_VALUES = {label: mode for mode, label in SCREENSHOT_LABELS.items()}
SCREENSHOT_EXPLAINED = {
    "full": "The whole game window, chat and your character name included.",
    "marker": "Just the marker. Nothing readable, so safe for a shared server.",
    "none": "Words only.",
}

WEBHOOK_HINT = "In Discord: Edit Channel > Integrations > Webhooks > New Webhook > Copy URL"
MENTION_HINT = "<@your-user-id> makes your phone buzz. Leave blank for silent."


def _not_a_webhook() -> str:
    """One wording for the two places that reject a URL.

    Naming only discord.com told people something narrower than the truth,
    since a discordapp.com webhook validates and works.
    """
    return (
        "That does not look like a webhook URL. "
        f"They start with https://{webhook_hosts_in_words()}, "
        "followed by /api/webhooks/"
    )


def ensure_config(path: Path = CONFIG) -> Path:
    """A config to edit, copied from the example the first time."""
    if not path.exists() and EXAMPLE_CONFIG.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
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
        return
    except OSError as exc:
        # No registered handler for .toml, which is the default on a clean
        # Windows install. Fall through to Notepad by absolute path.
        log.debug("No association for %s (%s); using Notepad.", path.suffix, exc)
    except Exception as exc:
        log.warning("Could not open %s: %s", path, exc)
        return

    notepad = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
    try:
        subprocess.Popen([str(notepad), str(path)])
    except Exception as exc:
        log.warning("Could not open %s in Notepad: %s", path, exc)


class SettingsWindow:
    """The handful of settings worth a dialog."""

    def __init__(self, path: Path = CONFIG, *, parent=None) -> None:
        import customtkinter as ctk

        ui.dark()
        self._ctk = ctk
        self._path = ensure_config(path)
        self._config = ConfigFile(self._path)
        self._parent = parent
        self._saved = False
        self.outcome = ""

        self._root = ctk.CTkToplevel(parent) if parent is not None else ctk.CTk()
        self._root.configure(fg_color=ui.WINDOW)
        self._root.title("Settings")
        self._root.resizable(False, False)
        ui.brand(self._root)
        self._mailbox = ui.Mailbox(self._root)

        current = self._current()
        self._webhook = tk.StringVar(value=current.webhook_url)
        self._mention = tk.StringVar(value=current.mention)
        self._to_discord = tk.BooleanVar(value="discord" in current.channels)
        self._to_desktop = tk.BooleanVar(value="desktop" in current.channels)
        self._discord_mode = tk.StringVar(value=MODE_LABELS[current.discord_mode])
        self._desktop_mode = tk.StringVar(value=MODE_LABELS[current.desktop_mode])
        self._screenshot = tk.StringVar(value=SCREENSHOT_LABELS[current.screenshot])
        self._poll = tk.StringVar(value=str(current.poll_interval_seconds))
        self._arrival = tk.StringVar(value=str(int(current.arrival_threshold_m)))
        self._stuck = tk.StringVar(value=str(int(current.stuck_after_seconds)))
        self._logging = tk.BooleanVar(value=current.log_to_file)

        self._build()
        if parent is not None:
            self._root.transient(parent)
            self._root.grab_set()
        self._root.lift()
        self._root.focus_force()

    def show(self) -> bool:
        """Run the dialog. True if the settings were saved."""
        if self._parent is not None:
            self._parent.wait_window(self._root)
        else:
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
        ctk = self._ctk
        body = ctk.CTkFrame(self._root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(18, 20))

        self._alerts(self._section(body, "Alerts"))
        self._discord(self._section(body, "Discord"))
        self._screenshots(self._section(body, "Screenshot in alerts"))
        self._timing(self._section(body, "Timing"))

        ctk.CTkSwitch(
            body,
            text="Write a log file, for chasing a misread",
            variable=self._logging,
            font=ui.font(),
            progress_color=ui.ACCENT,
        ).pack(anchor="w", pady=(14, 0))

        self._notice = ctk.CTkLabel(
            body, text="", text_color=ui.MUTED, font=ui.font(12), wraplength=560, justify="left"
        )
        self._notice.pack(anchor="w", pady=(14, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 0))
        self._quiet_button(buttons, "Open config file", self._open_file).pack(side="left")
        self._accent_button(buttons, "Save", self._save).pack(side="right")
        self._quiet_button(buttons, "Cancel", self._root.destroy).pack(side="right", padx=(0, 8))

    def _section(self, parent, title: str):
        ctk = self._ctk
        ctk.CTkLabel(parent, text=title, font=ui.font(12, weight="bold"), text_color=ui.MUTED).pack(
            anchor="w", pady=(12, 4)
        )
        card = ctk.CTkFrame(parent, fg_color=ui.CARD, corner_radius=10)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        return inner

    def _alerts(self, card) -> None:
        ctk = self._ctk
        for label, enabled, mode in (
            ("Discord", self._to_discord, self._discord_mode),
            ("Windows notifications", self._to_desktop, self._desktop_mode),
        ):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkSwitch(
                row, text=label, variable=enabled, font=ui.font(), progress_color=ui.ACCENT
            ).pack(side="left")
            ctk.CTkSegmentedButton(
                row,
                values=list(MODE_LABELS.values()),
                variable=mode,
                font=ui.font(12),
                selected_color=ui.ACCENT,
                selected_hover_color=ui.ACCENT_HOVER,
                unselected_color=ui.FIELD,
                unselected_hover_color=ui.QUIET,
            ).pack(side="right")
        self._hint(card, "Important only skips the heartbeat and sends what needs you.")

    def _discord(self, card) -> None:
        ctk = self._ctk
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x")
        self._entry(row, self._webhook, "https://discord.com/api/webhooks/...").pack(
            side="left", fill="x", expand=True
        )
        self._quiet_button(row, "Test", self._test, width=70).pack(side="left", padx=(8, 0))
        self._hint(card, WEBHOOK_HINT)

        ctk.CTkLabel(card, text="Mention", font=ui.font(12), text_color=ui.MUTED).pack(
            anchor="w", pady=(10, 2)
        )
        self._entry(card, self._mention, "<@123456789012345678>").pack(fill="x")
        self._hint(card, MENTION_HINT)

    def _screenshots(self, card) -> None:
        ctk = self._ctk
        ctk.CTkSegmentedButton(
            card,
            values=list(SCREENSHOT_LABELS.values()),
            variable=self._screenshot,
            command=lambda _choice: self._explain_screenshot(),
            font=ui.font(12),
            selected_color=ui.ACCENT,
            selected_hover_color=ui.ACCENT_HOVER,
            unselected_color=ui.FIELD,
            unselected_hover_color=ui.QUIET,
        ).pack(anchor="w")
        self._screenshot_hint = self._hint(card, "")
        self._explain_screenshot()

    def _timing(self, card) -> None:
        ctk = self._ctk
        for label, variable, unit, hint in (
            ("Check every", self._poll, "seconds", "30 is a good default"),
            ("Arrived under", self._arrival, "metres", "70, it rarely reaches 0"),
            ("Stuck after", self._stuck, "seconds", "180 before it calls it stuck"),
        ):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label, font=ui.font(), width=120, anchor="w").pack(side="left")
            self._entry(row, variable, "", width=70).pack(side="left")
            ctk.CTkLabel(row, text=unit, font=ui.font(12), text_color=ui.MUTED).pack(
                side="left", padx=(8, 0)
            )
            ctk.CTkLabel(row, text=hint, font=ui.font(12), text_color=ui.MUTED).pack(side="right")

    def _entry(self, parent, variable: tk.StringVar, placeholder: str, *, width: int = 140):
        return self._ctk.CTkEntry(
            parent,
            textvariable=variable,
            placeholder_text=placeholder,
            width=width,
            height=32,
            font=ui.font(),
            fg_color=ui.FIELD,
            border_color=ui.FIELD_BORDER,
            corner_radius=6,
        )

    def _hint(self, parent, text: str):
        label = self._ctk.CTkLabel(
            parent, text=text, font=ui.font(12), text_color=ui.MUTED, wraplength=540, justify="left"
        )
        label.pack(anchor="w", pady=(4, 0))
        return label

    def _quiet_button(self, parent, text: str, command, *, width: int = 130):
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

    def _accent_button(self, parent, text: str, command, *, width: int = 110):
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

    # -- actions ---------------------------------------------------------

    def _explain_screenshot(self) -> None:
        mode = SCREENSHOT_VALUES.get(self._screenshot.get(), "full")
        self._screenshot_hint.configure(text=SCREENSHOT_EXPLAINED[mode])

    def _say(self, text: str, colour: str = ui.MUTED) -> None:
        self._notice.configure(text=text, text_color=colour)

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
                return "Discord needs a webhook URL, or switch Discord off."
            if not is_webhook(webhook):
                return _not_a_webhook()

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
        """Send a test alert without freezing the window while Discord answers."""
        from .alerts import Alert
        from .discord import Discord

        webhook = self._webhook.get().strip()
        mention = self._mention.get().strip()
        if not is_webhook(webhook):
            self._say(_not_a_webhook(), ui.WARNING)
            return
        self._say("Sending a test alert...")

        def send() -> None:
            try:
                sent = Discord(webhook, mention).deliver(Alert.test_message())
            except Exception as exc:
                reason = scrubbed(str(exc), webhook)
                self._mailbox.post(lambda: self._say(f"Could not send. {reason}", ui.DANGER))
                return
            if sent:
                self._mailbox.post(lambda: self._say("Sent. Check your Discord channel.", ui.GOOD))
            else:
                self._mailbox.post(
                    lambda: self._say("Discord rejected it. Is the URL still valid?", ui.DANGER)
                )

        threading.Thread(target=send, daemon=True).start()

    def _open_file(self) -> None:
        open_in_editor(self._path)

    def _save(self) -> None:
        complaint = self._complaint()
        if complaint:
            self._say(complaint, ui.WARNING)
            return

        self._config.set("notify", "channels", self._channels())
        self._config.set(
            "notify", "discord_webhook_url", protected(self._webhook.get().strip())
        )
        self._config.set("notify", "mention", self._mention.get().strip())
        self._config.set("notify", "discord_mode", MODE_VALUES[self._discord_mode.get()])
        self._config.set("notify", "desktop_mode", MODE_VALUES[self._desktop_mode.get()])
        self._config.set("notify", "screenshot", SCREENSHOT_VALUES[self._screenshot.get()])
        self._config.set("capture", "poll_interval_seconds", int(self._poll.get()))
        self._config.set("detect", "arrival_threshold_m", float(self._arrival.get()))
        self._config.set("detect", "stuck_after_seconds", int(self._stuck.get()))
        self._config.set("logging", "to_file", bool(self._logging.get()))
        self._config.save()

        self._saved = True
        stored = "encrypted for this Windows account" if available() else "stored as plain text"
        self.outcome = f"Settings saved. The webhook is {stored}."
        log.info("Settings saved to %s", self._path)
        self._mailbox.close()
        self._root.destroy()
