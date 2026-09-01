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
from .discord import Discord
from .marker import Marker, Sighting
from .monitor import Monitor, build_marker, build_readout, build_voyage
from .observation import Observation
from .picker import digits_and_icon
from .readout import Readout
from .settings import ICON, ROOT, Calibration, Settings, SettingsError
from .window import Window, blank, capture_for

log = logging.getLogger("bdo_autoroute")

CAPTURES = ROOT / "captures"
LOGS = ROOT / "logs"
DEBUG = ROOT / "debug"
SAMPLES = ROOT / "samples"


def frame_of(window: Window, method: str) -> Image.Image:
    with capture_for(method) as capture:
        return capture.frame(window)


def windows(settings: Settings, _args) -> int:
    """List visible windows, so a wrong title match is easy to spot."""
    everything = Window.all()
    needles = [t.lower() for t in settings.title_matches]
    matched = [w for w in everything if any(n in w[1].lower() for n in needles)]

    log.info("Windows matching %s:", settings.title_matches)
    for hwnd, title in matched or []:
        log.info("  [MATCH] hwnd=%d  %r", hwnd, title)
    if not matched:
        log.warning("  none")

    log.info("All %d visible windows:", len(everything))
    for hwnd, title in everything:
        log.info("    hwnd=%d  %r", hwnd, title)
    return 0 if matched else 1


def calibrate(settings: Settings, _args) -> int:
    window = Window.matching(settings.title_matches)
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
    window = Window.matching(settings.title_matches)
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


def test_notify(settings: Settings, _args) -> int:
    discord = Discord(settings.webhook_url, settings.mention)
    alert = Alert.test_message()
    if settings.attach_screenshot:
        try:
            window = Window.matching(settings.title_matches)
            alert = alert.showing(frame_of(window, settings.capture_method))
        except Exception as exc:
            log.warning("Could not grab a screenshot (%s); sending without one.", exc)

    if discord.deliver(alert):
        log.info("Test alert delivered.")
        return 0
    log.error("Test alert failed. Check notify.discord_webhook_url in config.toml.")
    return 2


def run(settings: Settings, args) -> int:
    monitor = Monitor(
        settings,
        Calibration.load(),
        build_readout(settings),
        Discord(settings.webhook_url, settings.mention),
        build_voyage(settings),
        working_dirs=(CAPTURES, DEBUG),
        samples_dir=SAMPLES,
    )
    return monitor.run(once=args.once)


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
