"""Command line entry points: calibrate, run, shot, test-notify, windows."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from types import FrameType

from PIL import Image, ImageDraw

from .calibrate import capture_frame, pick_boxes, save_preview, warn_if_black
from .capture import (
    CaptureError,
    FrameGrabber,
    WindowMinimisedError,
    find_client_area,
    list_windows,
    looks_black,
    make_grabber,
)
from .config import (
    REPO_ROOT,
    TEMPLATE_PATH,
    Calibration,
    Config,
    ConfigError,
    load_calibration,
    load_config,
    save_calibration,
)
from .detector import Event, State, Status, VoyageDetector, format_duration
from .locator import LocatorError, MarkerLocator, digits_offset_from_boxes
from .notify import DiscordNotifier, NotifyError
from .ocr import DistanceReader, OcrError, make_backend
from .storage import SampleArchive, prune_directory

DEBUG_DIR = REPO_ROOT / "debug"
CAPTURES_DIR = REPO_ROOT / "captures"
SAMPLES_DIR = REPO_ROOT / "samples"

log = logging.getLogger("bdo_tracker")

_TITLES = {
    State.ARRIVED: "Boat has arrived",
    State.STUCK: "Boat looks stuck",
    State.SIGNAL_LOST: "Lost sight of the boat",
    State.SAILING: "Under way",
    State.STARTING: "Starting up",
}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_reader(cfg: Config) -> DistanceReader:
    return DistanceReader(
        make_backend(cfg.ocr_backend),
        upscale=cfg.upscale,
        brightness_threshold=cfg.brightness_threshold,
        min_valid_m=cfg.min_valid_m,
        max_valid_m=cfg.max_valid_m,
    )


def _build_locator(cfg: Config, calibration: Calibration, client_w: int, client_h: int):
    template = Image.open(REPO_ROOT / calibration.template_path).convert("RGB")
    scale = calibration.scale_for(client_w, client_h)
    if abs(scale - 1.0) > 0.01:
        log.info(
            "Resolution differs from calibration (%dx%d -> %dx%d); scaling by %.3f.",
            calibration.client_width,
            calibration.client_height,
            client_w,
            client_h,
            scale,
        )
    return MarkerLocator(
        template,
        calibration.digits_offset,
        match_threshold=cfg.match_threshold,
        scale=scale,
    )


def _report_threshold_margin(cfg: Config, locator: MarkerLocator, frame, match) -> None:
    """Measure how well the marker separates from ordinary scenery.

    The template is small, so scenery can score surprisingly high. Blanking out
    the marker and re-matching gives the noise floor for this exact setup, which
    beats trusting a hard-coded default.
    """
    ix, iy, iw, ih = match.icon_box
    dx, dy, dw, dh = match.digits_box
    blanked = frame.copy()
    draw = ImageDraw.Draw(blanked)
    draw.rectangle([ix, iy, ix + iw, iy + ih], fill=(0, 0, 0))
    draw.rectangle([dx, dy, dx + dw, dy + dh], fill=(0, 0, 0))

    floor = locator.best_confidence(blanked)
    log.info(
        "Match confidence: %.3f with the marker, %.3f without it (scenery noise floor).",
        match.confidence,
        floor,
    )

    suggested = round(min(0.95, floor + (match.confidence - floor) / 2), 2)
    if cfg.match_threshold <= floor:
        log.error(
            "marker.match_threshold is %.2f, at or BELOW the %.3f noise floor. "
            "Scenery will be mistaken for the marker and a made-up distance "
            "reported. Raise it to about %.2f in config.toml.",
            cfg.match_threshold,
            floor,
            suggested,
        )
    elif cfg.match_threshold < floor + 0.05:
        log.warning(
            "marker.match_threshold (%.2f) is only just above the %.3f noise "
            "floor. Consider raising it to about %.2f.",
            cfg.match_threshold,
            floor,
            suggested,
        )
    else:
        log.info(
            "marker.match_threshold %.2f sits comfortably between them.",
            cfg.match_threshold,
        )


def _annotate(frame: Image.Image, match) -> Image.Image:
    """Draw the icon and digits boxes onto a copy of the frame."""
    annotated = frame.copy()
    draw = ImageDraw.Draw(annotated)
    ix, iy, iw, ih = match.icon_box
    dx, dy, dw, dh = match.digits_box
    draw.rectangle([ix, iy, ix + iw, iy + ih], outline=(255, 80, 80), width=2)
    draw.rectangle([dx, dy, dx + dw, dy + dh], outline=(0, 255, 136), width=2)
    return annotated


# -- commands ------------------------------------------------------------


def cmd_windows(cfg: Config, _args: argparse.Namespace) -> int:
    """List visible windows so a wrong title match is easy to spot."""
    all_windows = list_windows()
    needles = [t.lower() for t in cfg.title_matches]
    log.info("Visible windows matching %s:", cfg.title_matches)
    matched = [(h, t) for h, t in all_windows if any(n in t.lower() for n in needles)]
    if matched:
        for hwnd, title in matched:
            log.info("  [MATCH] hwnd=%d  %r", hwnd, title)
    else:
        log.warning("  none")
    log.info("All %d visible windows:", len(all_windows))
    for hwnd, title in all_windows:
        log.info("    hwnd=%d  %r", hwnd, title)
    return 0 if matched else 1


def cmd_calibrate(cfg: Config, _args: argparse.Namespace) -> int:
    area = find_client_area(cfg.title_matches)
    log.info("Found %r at %dx%d", area.title, area.width, area.height)

    frame = capture_frame(area, cfg.capture_method)
    if warn_if_black(frame):
        return 2

    boxes = pick_boxes(frame)
    if boxes is None:
        log.info("Calibration cancelled; nothing was saved.")
        return 1
    digits_box, icon_box = boxes

    icon = frame.crop(
        (icon_box[0], icon_box[1], icon_box[0] + icon_box[2], icon_box[1] + icon_box[3])
    )
    icon.save(TEMPLATE_PATH)

    offset = digits_offset_from_boxes(digits_box, icon_box, left_slack=cfg.left_slack)
    calibration = Calibration(
        digits_offset=offset,
        client_width=area.width,
        client_height=area.height,
        template_path=TEMPLATE_PATH.name,
    )
    path = save_calibration(calibration)
    log.info("Saved %s and %s", path.name, TEMPLATE_PATH.name)
    log.info(
        "Icon template %dx%d; digits box %dx%d at offset (%d, %d) from the icon.",
        icon.width,
        icon.height,
        offset[2],
        offset[3],
        offset[0],
        offset[1],
    )

    # Prove the whole pipeline works on this very frame.
    locator = _build_locator(cfg, calibration, area.width, area.height)
    match = locator.locate(frame)
    if match is None:
        log.error(
            "The icon template could not be re-found in the same frame. "
            "Re-run calibrate and box the icon more tightly."
        )
        return 3

    crop = locator.crop_digits(frame, match)
    reader = _build_reader(cfg)
    written = save_preview(
        {
            "calibration_icon": icon,
            "calibration_crop": crop,
            "calibration_prepared": reader.prepare(crop),
            "calibration_annotated": _annotate(frame, match),
        },
        DEBUG_DIR,
    )
    log.info("Wrote %s", ", ".join(p.name for p in written))
    log.info("Icon re-found with confidence %.3f", match.confidence)
    _report_threshold_margin(cfg, locator, frame, match)

    reading = reader.read(crop)
    if reading.ok:
        log.info("Read %.0fm. Calibration looks good.", reading.meters)
        return 0

    log.warning("Could not read a distance. OCR returned: %r", reading.raw_text)
    log.warning(
        "Open debug/calibration_prepared.png. If the digits are not crisp black on "
        "white, adjust ocr.brightness_threshold in config.toml (lower keeps more "
        "pixels) and re-run calibrate. debug/calibration_annotated.png shows which "
        "part of the screen was read."
    )
    return 3


def cmd_shot(cfg: Config, _args: argparse.Namespace) -> int:
    """Save a frame, and if calibrated, the located marker and its reading."""
    area = find_client_area(cfg.title_matches)
    log.info("Found %r at %dx%d", area.title, area.width, area.height)
    frame = capture_frame(area, cfg.capture_method)

    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    frame_path = CAPTURES_DIR / f"frame-{stamp}.png"
    frame.save(frame_path)
    log.info("Saved %s (%dx%d)", frame_path.name, frame.width, frame.height)

    if looks_black(frame):
        log.error(
            "The frame is all black. Switch Black Desert to Borderless Windowed "
            "under Settings > Display."
        )
        return 2

    try:
        calibration = load_calibration()
    except ConfigError:
        log.info("No calibration yet. Run .\\calibrate.ps1 next.")
        return 0

    locator = _build_locator(cfg, calibration, area.width, area.height)
    match = locator.locate(frame)
    if match is None:
        log.warning(
            "Route marker not found in this frame (below match_threshold=%.2f). "
            "Is an auto-route active and the marker on screen?",
            cfg.match_threshold,
        )
        return 3

    log.info(
        "Marker found at %s with confidence %.3f", match.icon_box[:2], match.confidence
    )
    if not match.has_digits:
        log.warning("Marker is at the screen edge; the digits are off-screen.")
        return 3
    crop = locator.crop_digits(frame, match)
    crop.save(CAPTURES_DIR / f"crop-{stamp}.png")
    _annotate(frame, match).save(CAPTURES_DIR / f"annotated-{stamp}.png")

    reader = _build_reader(cfg)
    reader.prepare(crop).save(CAPTURES_DIR / f"prepared-{stamp}.png")
    reading = reader.read(crop)
    log.info(
        "Readout is %s (red ratio %.2f)",
        "RED - close to destination" if reading.near_indicator else "normal colour",
        reading.red_ratio,
    )
    if reading.ok:
        log.info("Reads %.0fm  (raw OCR: %r)", reading.meters, reading.raw_text)
        return 0
    log.warning("Did not parse. Raw OCR: %r", reading.raw_text)
    return 3


def cmd_test_notify(cfg: Config, _args: argparse.Namespace) -> int:
    notifier = DiscordNotifier(cfg.discord_webhook_url, cfg.mention)
    screenshot = None
    if cfg.attach_screenshot:
        try:
            screenshot = capture_frame(find_client_area(cfg.title_matches), cfg.capture_method)
        except CaptureError as exc:
            log.warning("Could not grab a screenshot (%s); sending without one.", exc)

    ok = notifier.send(
        title="Test alert",
        description="If you can read this, the webhook is wired up correctly.",
        state="SAILING",
        fields={"Source": "bdo-barter-tracker", "Kind": "manual test"},
        screenshot=screenshot,
        ping=bool(cfg.mention),
    )
    if ok:
        log.info("Test alert delivered.")
        return 0
    log.error("Test alert failed. Check notify.discord_webhook_url in config.toml.")
    return 2


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    calibration = load_calibration()
    reader = _build_reader(cfg)
    notifier = DiscordNotifier(cfg.discord_webhook_url, cfg.mention)
    detector = VoyageDetector(
        arrival_threshold_m=cfg.arrival_threshold_m,
        movement_epsilon_m=cfg.movement_epsilon_m,
        stuck_after_seconds=cfg.stuck_after_seconds,
        missing_confirm_polls=cfg.missing_confirm_polls,
        near_arrival_m=cfg.near_arrival_m,
        arrival_confirm_polls=cfg.arrival_confirm_polls,
    )
    return Monitor(cfg, calibration, reader, notifier, detector).run(once=args.once)


# -- the monitor loop ----------------------------------------------------


class Monitor:
    def __init__(
        self,
        cfg: Config,
        calibration: Calibration,
        reader: DistanceReader,
        notifier: DiscordNotifier,
        detector: VoyageDetector,
    ) -> None:
        self._cfg = cfg
        self._calibration = calibration
        self._reader = reader
        self._notifier = notifier
        self._detector = detector
        self._locator: MarkerLocator | None = None
        self._locator_size: tuple[int, int] | None = None
        self._stopping = False
        self._last_heartbeat = 0.0
        self._last_stuck_alert = 0.0
        self._warned_black = False
        self._archive = SampleArchive(
            root=SAMPLES_DIR,
            max_per_category=cfg.samples_max_per_category,
            min_interval_seconds=cfg.sample_every_minutes * 60,
            enabled=cfg.samples_enabled,
        )

    def request_stop(self, _signum: int, _frame: FrameType | None) -> None:
        log.info("Stop requested; finishing the current poll.")
        self._stopping = True

    def run(self, *, once: bool = False) -> int:
        signal.signal(signal.SIGINT, self.request_stop)
        self._housekeeping()
        interval = self._cfg.poll_interval_seconds
        log.info(
            "Monitoring every %ds. Heartbeat every %s. Ctrl+C to stop.",
            interval,
            f"{self._cfg.heartbeat_minutes} min" if self._cfg.heartbeat_minutes else "never",
        )

        with make_grabber(self._cfg.capture_method) as grabber:
            while not self._stopping:
                try:
                    self._poll(grabber)
                except WindowMinimisedError as exc:
                    # Distinct from a crash, and worth saying so in the alert.
                    log.warning("%s", exc)
                    self._handle_capture_failure(str(exc), minimised=True)
                except (CaptureError, LocatorError) as exc:
                    # The game closing mid-voyage is itself worth knowing about.
                    log.warning("Poll failed: %s", exc)
                    self._handle_capture_failure(str(exc))
                except Exception:  # noqa: BLE001 - the loop must survive surprises
                    log.exception("Unexpected error during poll; continuing.")

                if once or self._stopping:
                    break
                time.sleep(interval)

        log.info("Monitor stopped.")
        return 0

    def _housekeeping(self) -> None:
        """Expire old working files. samples/ is curated and deliberately spared."""
        removed = sum(
            prune_directory(d, self._cfg.retain_days) for d in (CAPTURES_DIR, DEBUG_DIR)
        )
        if removed:
            log.info(
                "Removed %d working file(s) older than %d days.",
                removed,
                self._cfg.retain_days,
            )
        if self._cfg.samples_enabled:
            counts = self._archive.counts()
            log.info(
                "Training samples held: %s",
                ", ".join(f"{k}={v}" for k, v in counts.items()) or "none",
            )

    def _archive_sample(
        self,
        frame: Image.Image,
        crop: Image.Image | None,
        match,
        reading,
        raw_text: str,
    ) -> None:
        """Keep a labelled sample, biased towards the cases worth learning from."""
        if not self._cfg.samples_enabled:
            return
        confidence = match.confidence if match is not None else 0.0
        category = SampleArchive.classify(
            found=match is not None and match.has_digits,
            parsed=reading is not None and reading.ok,
            red=reading is not None and reading.near_indicator,
            confidence=confidence,
            match_threshold=self._cfg.match_threshold,
        )
        # A no-marker sample only means anything as a whole frame.
        image = crop if (crop is not None and category != "no_marker") else frame
        self._archive.record(
            category,
            image,
            {
                "raw_ocr": raw_text,
                "meters": None if reading is None else reading.meters,
                "red_ratio": None if reading is None else round(reading.red_ratio, 3),
                "match_confidence": round(confidence, 4),
                "match_threshold": self._cfg.match_threshold,
                "icon_box": None if match is None else list(match.icon_box),
                "digits_box": None if match is None else list(match.digits_box),
                "state": self._detector.state.value,
                "capture_method": self._cfg.capture_method,
            },
        )

    def _locator_for(self, client_w: int, client_h: int) -> MarkerLocator:
        """Build the locator lazily, and rebuild it if the resolution changed."""
        if self._locator is None or self._locator_size != (client_w, client_h):
            self._locator = _build_locator(self._cfg, self._calibration, client_w, client_h)
            self._locator_size = (client_w, client_h)
        return self._locator

    def _poll(self, grabber: FrameGrabber) -> None:
        area = find_client_area(self._cfg.title_matches)
        frame = grabber.grab_client(area)

        if looks_black(frame):
            if not self._warned_black:
                log.error(
                    "Captured frame is all black. Switch Black Desert to Borderless "
                    "Windowed under Settings > Display."
                )
                self._warned_black = True
        else:
            self._warned_black = False

        locator = self._locator_for(area.width, area.height)
        match = locator.locate(frame)
        distance = None
        raw_text = "<marker not found>"
        confidence = 0.0
        near_indicator = False
        crop = None
        reading = None

        if match is not None:
            confidence = match.confidence
            if not match.has_digits:
                # Seen, but jammed against a screen edge with the digits cut off.
                raw_text = "<marker at screen edge, digits off-screen>"
            else:
                crop = locator.crop_digits(frame, match)
                reading = self._reader.read(crop)
                distance = reading.meters
                raw_text = reading.raw_text
                near_indicator = reading.near_indicator
                if self._cfg.save_crops:
                    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    crop.save(DEBUG_DIR / f"crop-{stamp}.png")

        self._archive_sample(frame, crop, match, reading, raw_text)

        now = time.monotonic()
        status = self._detector.update(distance, now, near_indicator=near_indicator)
        self._log_status(status, raw_text, confidence, near_indicator)
        self._dispatch(status, frame, now)

    def _handle_capture_failure(self, reason: str, *, minimised: bool = False) -> None:
        """Treat a vanished or minimised game window as a lost signal.

        Alerting is right even when the user minimised deliberately: silence
        would let them walk away believing the boat is still being watched.
        """
        now = time.monotonic()
        status = self._detector.update(None, now)
        if status.event is None:
            return
        label = "Game minimised" if minimised else "Error"
        self._send_event(status.event, None, extra={label: reason[:200]})

    def _log_status(
        self, status: Status, raw_text: str, confidence: float, near_indicator: bool
    ) -> None:
        distance = f"{status.distance_m:.0f}m" if status.distance_m is not None else "unknown"
        eta = format_duration(status.eta_seconds) if status.eta_seconds else "-"
        suffix = f"  match={confidence:.2f} raw={raw_text!r}" if status.distance_m is None else ""
        if near_indicator:
            suffix += "  [readout is red - close to destination]"
        log.info(
            "%-11s distance=%-9s eta=%-9s stalled=%s%s",
            status.state.value,
            distance,
            eta,
            format_duration(status.stalled_seconds),
            suffix,
        )

    def _dispatch(self, status: Status, frame: Image.Image | None, now: float) -> None:
        if status.event is not None:
            if status.event.state is State.STUCK:
                self._last_stuck_alert = now
            self._send_event(status.event, frame)
            return

        # A boat that stays stuck should nag periodically, not only on the edge.
        if status.state is State.STUCK:
            self._maybe_restuck(status, frame, now)
            return

        self._maybe_heartbeat(status, frame, now)

    def _maybe_restuck(self, status: Status, frame: Image.Image | None, now: float) -> None:
        cooldown = self._cfg.stuck_realert_minutes * 60
        if not cooldown or now - self._last_stuck_alert < cooldown:
            return
        self._last_stuck_alert = now
        remaining = (
            f"{status.distance_m:.0f}m still to go."
            if status.distance_m is not None
            else "Distance unknown."
        )
        self._send(
            title="Boat is still stuck",
            description=f"No progress for {format_duration(status.stalled_seconds)}. {remaining}",
            state=status.state,
            frame=frame,
            ping=True,
        )

    def _maybe_heartbeat(self, status: Status, frame: Image.Image | None, now: float) -> None:
        if not self._cfg.heartbeat_minutes or status.state is not State.SAILING:
            return
        interval = self._cfg.heartbeat_minutes * 60
        if self._last_heartbeat and now - self._last_heartbeat < interval:
            return
        self._last_heartbeat = now
        self._send(
            title="Still sailing",
            description=f"{status.distance_m:.0f}m remaining.",
            state=status.state,
            frame=frame,
            ping=False,
            fields={"ETA": format_duration(status.eta_seconds)},
        )

    def _send_event(
        self, event: Event, frame: Image.Image | None, extra: dict[str, str] | None = None
    ) -> None:
        fields = {"Was": event.previous.value}
        if event.eta_seconds:
            fields["ETA"] = format_duration(event.eta_seconds)
        if extra:
            fields.update(extra)
        title = (
            "Possible arrival" if event.pending_arrival
            else _TITLES.get(event.state, event.state.value)
        )
        self._send(
            title=title,
            description=event.message,
            state=event.state,
            frame=frame,
            ping=event.state.value in self._cfg.ping_on,
            fields=fields,
        )

    def _send(
        self,
        *,
        title: str,
        description: str,
        state: State,
        frame: Image.Image | None,
        ping: bool,
        fields: dict[str, str] | None = None,
    ) -> None:
        screenshot = frame if (self._cfg.attach_screenshot and frame is not None) else None
        stamped = dict(fields or {})
        stamped["Time"] = datetime.now().strftime("%H:%M:%S")
        if self._notifier.send(
            title=title,
            description=description,
            state=state.value,
            fields=stamped,
            screenshot=screenshot,
            ping=ping,
        ):
            log.info("Alert sent: %s", title)


# -- argument parsing ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bdo-tracker",
        description=(
            "Watch the Black Desert auto-route distance readout and alert on "
            "arrival or a stuck boat."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("calibrate", help="box the distance digits and the icon (do this first)")

    run = sub.add_parser("run", help="start monitoring")
    run.add_argument("--once", action="store_true", help="poll a single time and exit")

    sub.add_parser("shot", help="save a frame and the located marker for troubleshooting")
    sub.add_parser("test-notify", help="send a test alert to the Discord webhook")
    sub.add_parser("windows", help="list visible windows and which ones match")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    handlers = {
        "calibrate": cmd_calibrate,
        "run": cmd_run,
        "shot": cmd_shot,
        "test-notify": cmd_test_notify,
        "windows": cmd_windows,
    }
    try:
        cfg = load_config()
        return handlers[args.command](cfg, args)
    except (ConfigError, CaptureError, NotifyError, OcrError, LocatorError) as exc:
        log.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        log.info("Interrupted.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
