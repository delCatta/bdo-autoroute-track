"""Loading of config.toml (hand-edited) and calibration.json (written by `calibrate`)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.toml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config.example.toml"
CALIBRATION_PATH = REPO_ROOT / "calibration.json"
TEMPLATE_PATH = REPO_ROOT / "icon_template.png"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Calibration:
    """Everything needed to find and read the marker again.

    The route marker follows a world position, so nothing here is an absolute
    screen location. `digits_offset` is relative to wherever the icon turns up.
    `client_width`/`client_height` record the resolution these pixel sizes were
    measured at, so a different resolution can be scaled for.
    """

    digits_offset: tuple[int, int, int, int]  # dx, dy, w, h relative to icon top-left
    client_width: int
    client_height: int
    template_path: str

    def scale_for(self, client_w: int, client_h: int) -> float:
        """Scale factor if the game is now running at a different resolution."""
        if self.client_width <= 0 or self.client_height <= 0:
            return 1.0
        return min(client_w / self.client_width, client_h / self.client_height)

    def as_dict(self) -> dict[str, object]:
        # Coerce to plain ints: numpy integers reach here from image analysis
        # and are not JSON serialisable.
        return {
            "digits_offset": [int(v) for v in self.digits_offset],
            "client_width": int(self.client_width),
            "client_height": int(self.client_height),
            "template_path": str(self.template_path),
        }


@dataclass
class Config:
    title_matches: list[str] = field(default_factory=lambda: ["Black Desert"])
    poll_interval_seconds: int = 30
    capture_method: str = "window"

    arrival_threshold_m: float = 70.0
    movement_epsilon_m: float = 15.0
    stuck_after_seconds: int = 180
    stuck_realert_minutes: int = 10
    missing_confirm_polls: int = 4
    near_arrival_m: float = 400.0
    arrival_confirm_polls: int = 2

    discord_webhook_url: str = ""
    attach_screenshot: bool = True
    heartbeat_minutes: int = 5
    mention: str = ""
    ping_on: list[str] = field(default_factory=lambda: ["ARRIVED", "STUCK", "SIGNAL_LOST"])

    ocr_backend: str = "rapidocr"
    upscale: int = 4
    brightness_threshold: int = 120
    min_valid_m: float = 0.0
    max_valid_m: float = 20000.0

    match_threshold: float = 0.85
    left_slack: float = 2.0

    retain_days: int = 7
    samples_enabled: bool = True
    samples_max_per_category: int = 200
    sample_every_minutes: int = 30

    save_crops: bool = False


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"No config found at {path}.\n"
            f"Copy {EXAMPLE_CONFIG_PATH.name} to {path.name} and set your Discord webhook URL."
        )
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    window = raw.get("window", {})
    capture = raw.get("capture", {})
    detect = raw.get("detect", {})
    notify = raw.get("notify", {})
    ocr = raw.get("ocr", {})
    marker = raw.get("marker", {})
    storage = raw.get("storage", {})
    debug = raw.get("debug", {})
    defaults = Config()

    cfg = Config(
        title_matches=window.get("title_matches", defaults.title_matches),
        poll_interval_seconds=capture.get("poll_interval_seconds", defaults.poll_interval_seconds),
        capture_method=capture.get("method", defaults.capture_method),
        arrival_threshold_m=detect.get("arrival_threshold_m", defaults.arrival_threshold_m),
        movement_epsilon_m=detect.get("movement_epsilon_m", defaults.movement_epsilon_m),
        stuck_after_seconds=detect.get("stuck_after_seconds", defaults.stuck_after_seconds),
        stuck_realert_minutes=detect.get("stuck_realert_minutes", defaults.stuck_realert_minutes),
        missing_confirm_polls=detect.get("missing_confirm_polls", defaults.missing_confirm_polls),
        near_arrival_m=detect.get("near_arrival_m", defaults.near_arrival_m),
        arrival_confirm_polls=detect.get(
            "arrival_confirm_polls", defaults.arrival_confirm_polls
        ),
        discord_webhook_url=notify.get("discord_webhook_url", defaults.discord_webhook_url),
        attach_screenshot=notify.get("attach_screenshot", defaults.attach_screenshot),
        heartbeat_minutes=notify.get("heartbeat_minutes", defaults.heartbeat_minutes),
        mention=notify.get("mention", defaults.mention),
        ping_on=notify.get("ping_on", defaults.ping_on),
        ocr_backend=ocr.get("backend", defaults.ocr_backend),
        upscale=ocr.get("upscale", defaults.upscale),
        brightness_threshold=ocr.get("brightness_threshold", defaults.brightness_threshold),
        min_valid_m=ocr.get("min_valid_m", defaults.min_valid_m),
        max_valid_m=ocr.get("max_valid_m", defaults.max_valid_m),
        match_threshold=marker.get("match_threshold", defaults.match_threshold),
        left_slack=marker.get("left_slack", defaults.left_slack),
        retain_days=storage.get("retain_days", defaults.retain_days),
        samples_enabled=storage.get("samples_enabled", defaults.samples_enabled),
        samples_max_per_category=storage.get(
            "samples_max_per_category", defaults.samples_max_per_category
        ),
        sample_every_minutes=storage.get("sample_every_minutes", defaults.sample_every_minutes),
        save_crops=debug.get("save_crops", defaults.save_crops),
    )

    if cfg.poll_interval_seconds < 1:
        raise ConfigError("capture.poll_interval_seconds must be at least 1.")
    if cfg.movement_epsilon_m < 0:
        raise ConfigError("detect.movement_epsilon_m cannot be negative.")
    if not 0.0 < cfg.match_threshold <= 1.0:
        raise ConfigError("marker.match_threshold must be between 0 and 1.")
    if cfg.capture_method not in {"window", "screen"}:
        raise ConfigError(
            f"Unknown capture.method {cfg.capture_method!r}; use 'window' or 'screen'."
        )
    if cfg.retain_days < 0:
        raise ConfigError("storage.retain_days cannot be negative.")
    if cfg.ocr_backend not in {"rapidocr", "tesseract"}:
        raise ConfigError(f"Unknown ocr.backend {cfg.ocr_backend!r}; use 'rapidocr' or 'tesseract'.")
    return cfg


def load_calibration(path: Path | None = None) -> Calibration:
    path = path or CALIBRATION_PATH
    if not path.exists():
        raise ConfigError(
            f"No calibration found at {path}.\n"
            "Run .\\calibrate.ps1 and box the distance digits, then the icon beside them."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        offset = tuple(int(v) for v in data["digits_offset"])
        if len(offset) != 4:
            raise ValueError("digits_offset needs exactly 4 numbers")
        calibration = Calibration(
            digits_offset=offset,  # type: ignore[arg-type]
            client_width=int(data["client_width"]),
            client_height=int(data["client_height"]),
            template_path=str(data["template_path"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{path} is malformed ({exc}); re-run calibrate.") from exc

    if calibration.digits_offset[2] <= 0 or calibration.digits_offset[3] <= 0:
        raise ConfigError(f"{path} has a zero-sized digits box; re-run calibrate.")
    if not (REPO_ROOT / calibration.template_path).exists():
        raise ConfigError(
            f"Icon template {calibration.template_path} is missing; re-run calibrate."
        )
    return calibration


def save_calibration(calibration: Calibration, path: Path | None = None) -> Path:
    path = path or CALIBRATION_PATH
    path.write_text(json.dumps(calibration.as_dict(), indent=2) + "\n", encoding="utf-8")
    return path
