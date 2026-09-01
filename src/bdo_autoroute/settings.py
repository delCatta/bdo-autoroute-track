"""Settings from config.toml, and the calibration written by `calibrate`."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from .marker import Box, Offset
from .vault import revealed

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config.toml"
EXAMPLE_CONFIG = ROOT / "config.example.toml"
CALIBRATION = ROOT / "calibration.json"
ICON = ROOT / "icon_template.png"

CAPTURE_METHODS = ("window", "screen")
SCREENSHOT_MODES = ("full", "marker", "none")
NOTIFY_MODES = ("verbose", "important")

# Every Discord webhook lives here. Checked on the config path as well as in
# the settings window, because hot reload means anything that can write
# config.toml could otherwise redirect full-window screenshots to another host
# without a restart and without a prompt.
WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"

# How much room to leave around the marker when cropping. Enough to see the
# destination name and the surrounding water, not the chat panel.
MARKER_CROP_MARGIN = 3.0
OCR_BACKENDS = ("rapidocr", "tesseract")


class SettingsError(RuntimeError):
    pass


def _legacy_screenshot(notify: dict, fallback: "Settings") -> str:
    """Honour the old boolean attach_screenshot if it is still in a config."""
    if "attach_screenshot" in notify:
        return "full" if notify["attach_screenshot"] else "none"
    return fallback.screenshot


@dataclass(frozen=True)
class Calibration:
    """Everything needed to find and read the marker again.

    Nothing here is an absolute screen position: the marker moves, so the digits
    are located relative to wherever the icon turns up.
    """

    offset: Offset
    width: int
    height: int
    icon_path: str

    def scale_for(self, width: int, height: int) -> float:
        if self.width <= 0 or self.height <= 0:
            return 1.0
        return min(width / self.width, height / self.height)

    def save(self, path: Path | None = None) -> Path:
        path = path or CALIBRATION
        path.write_text(
            json.dumps(
                {
                    "digits_offset": [int(v) for v in self.offset.as_tuple()],
                    "client_width": int(self.width),
                    "client_height": int(self.height),
                    "template_path": str(self.icon_path),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "Calibration":
        path = path or CALIBRATION
        if not path.exists():
            raise SettingsError(
                f"No calibration at {path}.\n"
                "Run .\\calibrate.ps1 and box the distance digits, then the icon."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            offset = Offset(*(int(v) for v in data["digits_offset"]))
            calibration = cls(
                offset=offset,
                width=int(data["client_width"]),
                height=int(data["client_height"]),
                icon_path=str(data["template_path"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SettingsError(f"{path} is malformed ({exc}); re-run calibrate.") from exc

        if offset.width <= 0 or offset.height <= 0:
            raise SettingsError(f"{path} has a zero-sized digits box; re-run calibrate.")
        if not (ROOT / calibration.icon_path).exists():
            raise SettingsError(f"{calibration.icon_path} is missing; re-run calibrate.")
        return calibration

    @classmethod
    def between(cls, digits: Box, icon: Box, *, left_slack: float, size: tuple[int, int]):
        return cls(
            offset=Offset.between(digits, icon, left_slack=left_slack),
            width=size[0],
            height=size[1],
            icon_path=ICON.name,
        )


@dataclass(frozen=True)
class Settings:
    process_matches: list[str] = field(default_factory=lambda: ["BlackDesert64.exe"])
    title_matches: list[str] = field(default_factory=lambda: ["Black Desert"])
    capture_method: str = "window"
    poll_interval_seconds: int = 30

    arrival_threshold_m: float = 70.0
    arrival_confirm_polls: int = 2
    movement_epsilon_m: float = 15.0
    stuck_after_seconds: int = 180
    stuck_realert_minutes: int = 10
    missing_confirm_polls: int = 4
    near_arrival_m: float = 400.0
    approaching_m: float = 500.0
    stalling_after_seconds: int = 60

    webhook_url: str = ""
    channels: list[str] = field(default_factory=lambda: ["discord", "desktop"])
    screenshot: str = "full"
    heartbeat_minutes: int = 1
    heartbeat_min_progress_m: float = 150.0
    mention: str = ""
    urgent_states: list[str] = field(
        default_factory=lambda: ["ARRIVED", "STUCK", "SIGNAL_LOST"]
    )
    # Discord hears everything, because a phone alert is cheap to ignore and
    # the heartbeat is what tells you the monitor is still alive. A toast is
    # not cheap to ignore, so the desktop hears only what needs a person.
    discord_mode: str = "verbose"
    desktop_mode: str = "important"

    ocr_backend: str = "rapidocr"
    upscale: int = 4
    brightness_threshold: int = 120
    floor_m: float = 0.0
    ceiling_m: float = 20000.0

    match_threshold: float = 0.85
    left_slack: float = 2.0

    log_to_file: bool = False
    log_max_mb: int = 2
    log_keep_files: int = 5

    retain_days: int = 7
    samples_enabled: bool = True
    samples_max_per_category: int = 200
    sample_every_minutes: int = 30
    save_crops: bool = False

    @property
    def notification_modes(self) -> dict[str, str]:
        """How much each channel wants to hear, keyed the way Outbox wants it."""
        return {"discord": self.discord_mode, "desktop": self.desktop_mode}

    @property
    def wants_screenshot(self) -> bool:
        return self.screenshot != "none"

    @property
    def crops_screenshot(self) -> bool:
        return self.screenshot == "marker"

    @property
    def log_max_bytes(self) -> int:
        return max(1, self.log_max_mb) * 1_000_000

    @property
    def stuck_realert_seconds(self) -> float:
        return self.stuck_realert_minutes * 60

    @property
    def heartbeat_seconds(self) -> float:
        return self.heartbeat_minutes * 60

    @property
    def sample_interval_seconds(self) -> float:
        return self.sample_every_minutes * 60

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG
        if not path.exists():
            raise SettingsError(
                f"No config at {path}.\n"
                f"Copy {EXAMPLE_CONFIG.name} to {path.name} and set your webhook URL."
            )
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

        settings = cls._from_sections(raw)
        settings._validate()
        return settings

    @classmethod
    def _from_sections(cls, raw: dict) -> "Settings":
        window = raw.get("window", {})
        capture = raw.get("capture", {})
        detect = raw.get("detect", {})
        notify = raw.get("notify", {})
        marker = raw.get("marker", {})
        ocr = raw.get("ocr", {})
        storage = raw.get("storage", {})
        logs = raw.get("logging", {})
        debug = raw.get("debug", {})
        fallback = cls()

        return cls(
            process_matches=window.get("process_matches", fallback.process_matches),
            title_matches=window.get("title_matches", fallback.title_matches),
            capture_method=capture.get("method", fallback.capture_method),
            poll_interval_seconds=capture.get(
                "poll_interval_seconds", fallback.poll_interval_seconds
            ),
            arrival_threshold_m=detect.get(
                "arrival_threshold_m", fallback.arrival_threshold_m
            ),
            arrival_confirm_polls=detect.get(
                "arrival_confirm_polls", fallback.arrival_confirm_polls
            ),
            movement_epsilon_m=detect.get("movement_epsilon_m", fallback.movement_epsilon_m),
            stuck_after_seconds=detect.get(
                "stuck_after_seconds", fallback.stuck_after_seconds
            ),
            stuck_realert_minutes=detect.get(
                "stuck_realert_minutes", fallback.stuck_realert_minutes
            ),
            missing_confirm_polls=detect.get(
                "missing_confirm_polls", fallback.missing_confirm_polls
            ),
            near_arrival_m=detect.get("near_arrival_m", fallback.near_arrival_m),
            approaching_m=detect.get("approaching_m", fallback.approaching_m),
            stalling_after_seconds=detect.get(
                "stalling_after_seconds", fallback.stalling_after_seconds
            ),
            webhook_url=revealed(notify.get("discord_webhook_url", fallback.webhook_url)),
            channels=notify.get("channels", fallback.channels),
            screenshot=notify.get("screenshot", _legacy_screenshot(notify, fallback)),
            heartbeat_minutes=notify.get("heartbeat_minutes", fallback.heartbeat_minutes),
            heartbeat_min_progress_m=notify.get(
                "heartbeat_min_progress_m", fallback.heartbeat_min_progress_m
            ),
            mention=notify.get("mention", fallback.mention),
            urgent_states=notify.get("ping_on", fallback.urgent_states),
            discord_mode=notify.get("discord_mode", fallback.discord_mode),
            desktop_mode=notify.get("desktop_mode", fallback.desktop_mode),
            match_threshold=marker.get("match_threshold", fallback.match_threshold),
            left_slack=marker.get("left_slack", fallback.left_slack),
            ocr_backend=ocr.get("backend", fallback.ocr_backend),
            upscale=ocr.get("upscale", fallback.upscale),
            brightness_threshold=ocr.get(
                "brightness_threshold", fallback.brightness_threshold
            ),
            floor_m=ocr.get("min_valid_m", fallback.floor_m),
            ceiling_m=ocr.get("max_valid_m", fallback.ceiling_m),
            log_to_file=logs.get("to_file", fallback.log_to_file),
            log_max_mb=logs.get("max_mb", fallback.log_max_mb),
            log_keep_files=logs.get("keep_files", fallback.log_keep_files),
            retain_days=storage.get("retain_days", fallback.retain_days),
            samples_enabled=storage.get("samples_enabled", fallback.samples_enabled),
            samples_max_per_category=storage.get(
                "samples_max_per_category", fallback.samples_max_per_category
            ),
            sample_every_minutes=storage.get(
                "sample_every_minutes", fallback.sample_every_minutes
            ),
            save_crops=debug.get("save_crops", fallback.save_crops),
        )

    def _validate(self) -> None:
        if self.poll_interval_seconds < 1:
            raise SettingsError("capture.poll_interval_seconds must be at least 1.")
        if self.movement_epsilon_m < 0:
            raise SettingsError("detect.movement_epsilon_m cannot be negative.")
        if not 0.0 < self.match_threshold <= 1.0:
            raise SettingsError("marker.match_threshold must be between 0 and 1.")
        if self.retain_days < 0:
            raise SettingsError("storage.retain_days cannot be negative.")
        if self.screenshot not in SCREENSHOT_MODES:
            raise SettingsError(
                f"Unknown notify.screenshot {self.screenshot!r}; use "
                f"{', '.join(repr(m) for m in SCREENSHOT_MODES)}."
            )
        unknown = [c for c in self.channels if c not in ("discord", "desktop")]
        if unknown:
            raise SettingsError(
                f"Unknown notify.channels {unknown}; use 'discord' and/or 'desktop'."
            )
        if self.webhook_url and not self.webhook_url.startswith(WEBHOOK_PREFIX):
            raise SettingsError(
                "notify.discord_webhook_url does not look like a Discord "
                f"webhook. They start with {WEBHOOK_PREFIX}"
            )
        for channel, mode in self.notification_modes.items():
            if mode not in NOTIFY_MODES:
                raise SettingsError(
                    f"Unknown notify.{channel}_mode {mode!r}; use "
                    f"{', '.join(repr(m) for m in NOTIFY_MODES)}."
                )
        if self.log_max_mb < 1:
            raise SettingsError("logging.max_mb must be at least 1.")
        if self.log_keep_files < 0:
            raise SettingsError("logging.keep_files cannot be negative.")
        if self.capture_method not in CAPTURE_METHODS:
            raise SettingsError(
                f"Unknown capture.method {self.capture_method!r}; use "
                f"{' or '.join(repr(m) for m in CAPTURE_METHODS)}."
            )
        if self.ocr_backend not in OCR_BACKENDS:
            raise SettingsError(
                f"Unknown ocr.backend {self.ocr_backend!r}; use "
                f"{' or '.join(repr(b) for b in OCR_BACKENDS)}."
            )
