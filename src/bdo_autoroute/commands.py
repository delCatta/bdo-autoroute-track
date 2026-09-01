"""The things the CLI can be asked to do.

Each command gets settings, does one job, and returns an exit code. Anything
worth more than a few lines belongs on an object instead.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from .alerts import Alert
from .desktop import Desktop
from .discord import Discord
from .outbox import Outbox
from .marker import Marker, Sighting
from .monitor import Monitor, build_marker, build_readout, build_voyage
from .observation import Observation
from .picker import digits_and_icon
from .readout import Readout
from .settings import CONFIG, ICON, ROOT, Calibration, Settings, SettingsError
from .window import Window, blank, capture_for, process_name

log = logging.getLogger("bdo_autoroute")

CAPTURES = ROOT / "captures"
LOGS = ROOT / "logs"
DEBUG = ROOT / "debug"
SAMPLES = ROOT / "samples"


def frame_of(window: Window, method: str) -> Image.Image:
    with capture_for(method) as capture:
        return capture.frame(window)


def scrub(settings: Settings, _args) -> int:
    """Build a report that is safe to attach to a public issue."""
    from .bundle import Bundle

    target = Bundle(ROOT, settings).write()
    size_kb = target.stat().st_size / 1024
    log.info("Report written to %s (%.0f KB)", target, size_kb)
    log.info("")
    log.info("It contains the log with every webhook token removed, the digit")
    log.info("crops, and your calibration. It does not contain config.toml,")
    log.info("whole window frames, or any window titles.")
    log.info("Open it and look before attaching it to an issue.")
    return 0


def windows(settings: Settings, _args) -> int:
    """List windows with their processes, so a wrong match is easy to spot."""
    everything = Window.all()
    wanted = [p.lower() for p in settings.process_matches]
    needles = [t.lower() for t in settings.title_matches]

    by_process = [w for w in everything if process_name(w[0]).lower() in wanted]
    by_title = [w for w in everything if any(n in w[1].lower() for n in needles)]

    log.info("Windows from %s:", settings.process_matches)
    for hwnd, title in by_process or []:
        log.info("  [GAME] hwnd=%-9d %-22s %r", hwnd, process_name(hwnd), title)
    if not by_process:
        log.warning("  none, so the game does not appear to be running")

    log.info("Windows whose title matches %s:", settings.title_matches)
    for hwnd, title in by_title or []:
        marker = "[GAME]" if (hwnd, title) in by_process else "[other]"
        log.info("  %-7s hwnd=%-9d %-22s %r", marker, hwnd, process_name(hwnd), title)
    if len(by_title) > 1:
        log.warning(
            "  %d windows share the title. Matching by process avoids picking "
            "the wrong one; titles are only the fallback.",
            len(by_title),
        )

    # Titles carry document names and browser tabs, and this log is the file
    # CONTRIBUTING.md asks people to attach to an issue. The count is enough to
    # explain an ambiguous match; the titles themselves need -v.
    log.info("All %d visible windows (run with -v to list them).", len(everything))
    for hwnd, title in everything:
        log.debug("    hwnd=%-9d %-22s %r", hwnd, process_name(hwnd), title)
    return 0 if by_process or by_title else 1


def calibrate(settings: Settings, _args) -> int:
    window = Window.matching(settings.title_matches, settings.process_matches)
    log.info("Found %r at %dx%d", window.title, window.width, window.height)

    frame = frame_of(window, settings.capture_method)
    if blank(frame):
        log.error(
            "The captured frame is entirely black. Black Desert is probably in "
            "Fullscreen Exclusive mode; switch it to Borderless Windowed."
        )
        return 2

    boxes = digits_and_icon(frame)
    if boxes is None:
        log.info("Cancelled; nothing was saved.")
        return 1

    digits, icon_box = boxes
    icon_box.crop(frame).save(ICON)
    calibration = Calibration.between(
        digits, icon_box, left_slack=settings.left_slack, size=window.size
    )
    calibration.save()
    log.info("Saved calibration.json and %s", ICON.name)

    marker = build_marker(settings, calibration, window.size)
    sighting = marker.sighting(frame)
    if sighting is None:
        log.error(
            "The icon could not be re-found in the same frame. Re-run calibrate "
            "and box the icon more tightly."
        )
        return 3

    readout = build_readout(settings)
    _write_previews(frame, sighting, readout)
    log.info("Icon re-found with confidence %.3f", sighting.confidence)
    _report_noise_floor(settings, marker, frame, sighting)

    reading = readout.reading(sighting.digits.crop(frame))
    if reading.understood:
        log.info("Read %.0fm. Calibration looks good.", reading.meters)
        return 0

    log.warning("Could not read a distance. OCR returned: %r", reading.raw_text)
    log.warning(
        "Open debug/stencil.png. If the digits are not crisp black on white, "
        "adjust ocr.brightness_threshold and re-run. debug/annotated.png shows "
        "which part of the screen was read."
    )
    return 3


def shot(settings: Settings, _args) -> int:
    """One look: where the marker is and what it reads."""
    window = Window.matching(settings.title_matches, settings.process_matches)
    log.info("Found %r at %dx%d", window.title, window.width, window.height)
    frame = frame_of(window, settings.capture_method)

    CAPTURES.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    frame.save(CAPTURES / f"frame-{stamp}.png")
    log.info("Saved frame-%s.png (%dx%d)", stamp, frame.width, frame.height)

    if blank(frame):
        log.error("The frame is entirely black. Switch to Borderless Windowed.")
        return 2

    try:
        calibration = Calibration.load()
    except SettingsError:
        log.info("No calibration yet. Run .\\calibrate.ps1 next.")
        return 0

    marker = build_marker(settings, calibration, window.size)
    sighting = marker.sighting(frame)
    if sighting is None:
        log.warning(
            "Marker not found (below match_threshold=%.2f). Is an auto-route "
            "active and the marker on screen?",
            settings.match_threshold,
        )
        return 3

    log.info("Marker at %s with confidence %.3f", sighting.icon.origin, sighting.confidence)
    if not sighting.readable:
        log.warning("Marker is at the screen edge; the digits are off screen.")
        return 3

    readout = build_readout(settings)
    crop = sighting.digits.crop(frame)
    crop.save(CAPTURES / f"crop-{stamp}.png")
    _annotated(frame, sighting).save(CAPTURES / f"annotated-{stamp}.png")
    readout.stencil(crop).save(CAPTURES / f"stencil-{stamp}.png")

    reading = readout.reading(crop)
    log.info(
        "Readout is %s (red ratio %.2f)",
        "RED, close to the destination" if reading.near_indicator else "normal colour",
        reading.red_ratio,
    )
    if reading.understood:
        log.info("Reads %.0fm  (raw OCR: %r)", reading.meters, reading.raw_text)
        return 0
    log.warning("Did not parse. Raw OCR: %r", reading.raw_text)
    return 3


def build_outbox(settings: Settings) -> Outbox:
    """Every channel that can actually be built, with a reason for any that cannot."""
    channels = []
    for name in settings.channels:
        try:
            channels.append(_channel(name, settings))
        except Exception as exc:
            log.warning("Channel %r unavailable, skipping: %s", name, exc)

    if not channels:
        log.error(
            "No usable notification channels. Set notify.discord_webhook_url, "
            'or add "desktop" to notify.channels.'
        )
    return Outbox(channels, settings.notification_modes)


def _channel(name: str, settings: Settings):
    if name == "discord":
        return Discord(settings.webhook_url, settings.mention)
    if name == "desktop":
        return Desktop(icon=ROOT / "assets" / "boat.ico")
    raise ValueError(f"unknown channel {name!r}")


def test_notify(settings: Settings, _args) -> int:
    outbox = build_outbox(settings)
    if outbox.empty:
        return 2

    alert = Alert.test_message()
    if settings.wants_screenshot:
        try:
            window = Window.matching(settings.title_matches, settings.process_matches)
            alert = alert.showing(frame_of(window, settings.capture_method))
        except Exception as exc:
            log.warning("Could not grab a screenshot (%s); sending without one.", exc)

    log.info("Sending a test alert to: %s", ", ".join(outbox.names))
    if outbox.deliver(alert):
        log.info("Test alert delivered.")
        return 0
    log.error("Test alert failed on every channel.")
    return 2


def run(settings: Settings, args) -> int:
    monitor = Monitor(
        settings,
        Calibration.load(),
        build_readout(settings),
        build_outbox(settings),
        build_voyage(settings),
        working_dirs=(CAPTURES, DEBUG),
        samples_dir=SAMPLES,
    )
    monitor.reloads_from(CONFIG, reloader)
    return monitor.run(once=args.once)


def configure(_settings: Settings | None, _args) -> int:
    """Open the settings window."""
    from .configure import SettingsWindow

    SettingsWindow().show()
    return 0


def protect(_settings: Settings | None, _args) -> int:
    """Encrypt the webhook already sitting in config.toml."""
    from .configfile import ConfigFile
    from .configure import ensure_config
    from .vault import PREFIX, available, masked, protected

    if not available():
        log.error("Windows DPAPI is unavailable, so the webhook cannot be encrypted.")
        return 2

    path = ensure_config()
    config = ConfigFile(path)
    stored = (config.get("notify", "discord_webhook_url") or "").strip().strip('"')

    if not stored:
        log.info("No webhook in %s; nothing to protect.", path.name)
        return 0
    if stored.startswith(PREFIX):
        log.info("The webhook in %s is already encrypted.", path.name)
        return 0

    config.set("notify", "discord_webhook_url", protected(stored))
    config.save()
    log.info(
        "Encrypted the webhook in %s (%s). It can now only be read by this "
        "Windows account on this machine.",
        path.name,
        masked(stored),
    )
    return 0


def reloader() -> tuple[Settings, Outbox]:
    """Fresh settings and a fresh outbox, for a monitor that spots a change."""
    from .cli import file_logging

    settings = Settings.load()
    file_logging(settings)
    return settings, build_outbox(settings)


def tray(settings: Settings, _args) -> int:
    """Run the monitor behind a system tray icon."""
    from .tray import Tray

    monitor = Monitor(
        settings,
        Calibration.load(),
        build_readout(settings),
        build_outbox(settings),
        build_voyage(settings),
        working_dirs=(CAPTURES, DEBUG),
        samples_dir=SAMPLES,
    )
    monitor.reloads_from(CONFIG, reloader)
    return Tray(monitor, icon=ROOT / "assets" / "boat.ico", logs=LOGS).run()


def _annotated(frame: Image.Image, sighting: Sighting) -> Image.Image:
    annotated = frame.copy()
    draw = ImageDraw.Draw(annotated)
    for box, colour in ((sighting.icon, (255, 80, 80)), (sighting.digits, (0, 255, 136))):
        draw.rectangle(
            [box.left, box.top, box.left + box.width, box.top + box.height],
            outline=colour,
            width=2,
        )
    return annotated


def _write_previews(frame: Image.Image, sighting: Sighting, readout: Readout) -> None:
    DEBUG.mkdir(parents=True, exist_ok=True)
    crop = sighting.digits.crop(frame)
    sighting.icon.crop(frame).save(DEBUG / "icon.png")
    crop.save(DEBUG / "crop.png")
    readout.stencil(crop).save(DEBUG / "stencil.png")
    _annotated(frame, sighting).save(DEBUG / "annotated.png")
    log.info("Wrote icon.png, crop.png, stencil.png and annotated.png to debug/")


def _report_noise_floor(
    settings: Settings, marker: Marker, frame: Image.Image, sighting: Sighting
) -> None:
    """Measure how far the marker stands out from ordinary scenery.

    The template is small, so scenery can score surprisingly high. Blanking the
    marker and re-matching gives the noise floor for this exact setup, which
    beats trusting a hard-coded default.
    """
    blanked = frame.copy()
    draw = ImageDraw.Draw(blanked)
    for box in (sighting.icon, sighting.digits):
        draw.rectangle(
            [box.left, box.top, box.left + box.width, box.top + box.height], fill=(0, 0, 0)
        )

    floor = marker.confidence_in(blanked)
    log.info(
        "Match confidence: %.3f with the marker, %.3f without it (scenery floor).",
        sighting.confidence,
        floor,
    )

    suggested = round(min(0.95, floor + (sighting.confidence - floor) / 2), 2)
    if settings.match_threshold <= floor:
        log.error(
            "marker.match_threshold is %.2f, at or BELOW the %.3f scenery floor. "
            "Scenery will be mistaken for the marker and a made-up distance "
            "reported. Raise it to about %.2f.",
            settings.match_threshold,
            floor,
            suggested,
        )
    elif settings.match_threshold < floor + 0.05:
        log.warning(
            "marker.match_threshold (%.2f) is only just above the %.3f scenery "
            "floor. Consider raising it to about %.2f.",
            settings.match_threshold,
            floor,
            suggested,
        )
    else:
        log.info("marker.match_threshold %.2f sits comfortably between them.", settings.match_threshold)
