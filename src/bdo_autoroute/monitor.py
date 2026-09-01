"""The polling loop.

Thin on purpose: it looks, tells the voyage what it saw, and passes on whatever
the voyage thinks is worth saying. The wording lives in Alert, the rules live in
Voyage, and finding things on screen lives in Marker and Readout.
"""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import FrameType

from PIL import Image

from .alerts import Alert
from .archive import Archive, expire
from .discord import Discord
from .marker import Marker, MarkerError
from .observation import Observation
from .readout import Readout
from .settings import Calibration, Settings
from .voyage import Status, Voyage, duration
from .window import CaptureError, Window, WindowMinimised, blank, capture_for

log = logging.getLogger("bdo_autoroute")


@dataclass
class Timer:
    """Something that should not happen more often than every `interval`.

    `last_at` is None rather than 0.0 for "never fired": a timer marked at
    monotonic time zero would otherwise read as never having fired at all.
    """

    interval: float
    last_at: float | None = None

    def due(self, now: float) -> bool:
        if not self.interval:
            return False
        return self.last_at is None or now - self.last_at >= self.interval

    def mark(self, now: float) -> None:
        self.last_at = now


class Monitor:
    """Watches one auto-route until told to stop."""

    def __init__(
        self,
        settings: Settings,
        calibration: Calibration,
        readout: Readout,
        discord: Discord,
        voyage: Voyage,
        *,
        working_dirs: tuple[Path, ...] = (),
        samples_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._calibration = calibration
        self._readout = readout
        self._discord = discord
        self._voyage = voyage
        self._working_dirs = working_dirs
        self._debug_dir = working_dirs[-1] if working_dirs else None

        self._marker: Marker | None = None
        self._marker_size: tuple[int, int] | None = None
        self._stopping = False
        self._warned_blank = False
        self._heartbeat = Timer(settings.heartbeat_seconds)
        self._last_heartbeat_distance: float | None = None
        self._nagging = Timer(settings.stuck_realert_seconds)
        self._archive = Archive(
            root=samples_dir or Path("samples"),
            max_per_category=settings.samples_max_per_category,
            min_interval_seconds=settings.sample_interval_seconds,
            enabled=settings.samples_enabled,
        )

    def run(self, *, once: bool = False) -> int:
        signal.signal(signal.SIGINT, self.stop)
        self._tidy_up()
        log.info(
            "Watching every %ds. Heartbeat %s. Ctrl+C to stop.",
            self._settings.poll_interval_seconds,
            f"every {self._settings.heartbeat_minutes} min"
            if self._settings.heartbeat_minutes
            else "off",
        )

        with capture_for(self._settings.capture_method) as capture:
            while not self._stopping:
                self._tick(capture)
                if once or self._stopping:
                    break
                time.sleep(self._settings.poll_interval_seconds)

        log.info("Stopped.")
        return 0

    def stop(self, _signum: int, _frame: FrameType | None) -> None:
        log.info("Stop requested; finishing this poll.")
        self._stopping = True

    def _tick(self, capture) -> None:
        try:
            self._poll(capture)
        except WindowMinimised as exc:
            log.warning("%s", exc)
            self._nothing_to_see(str(exc), minimised=True)
        except (CaptureError, MarkerError) as exc:
            log.warning("Poll failed: %s", exc)
            self._nothing_to_see(str(exc))
        except Exception:
            log.exception("Unexpected error during poll; continuing.")

    def _poll(self, capture) -> None:
        window = Window.matching(self._settings.title_matches)
        observation = self._look(capture.frame(window), window.size)
        self._archive.keep(observation, match_threshold=self._settings.match_threshold)
        self._save_crop(observation)

        now = time.monotonic()
        status = self._voyage.update(
            observation.distance, now, near_indicator=observation.near_indicator
        )
        self._report(status, observation)
        self._announce(status, observation.frame, now)

    def _look(self, frame: Image.Image, size: tuple[int, int]) -> Observation:
        self._warn_once_if_blank(frame)
        marker = self._marker_for(size)
        sighting = marker.sighting(frame)
        if sighting is None or not sighting.readable:
            return Observation(frame=frame, sighting=sighting)
        return Observation(
            frame=frame,
            sighting=sighting,
            reading=self._readout.reading(sighting.digits.crop(frame)),
        )

    def _announce(self, status: Status, frame: Image.Image, now: float) -> None:
        if status.approaching:
            self._send(Alert.approaching(status), frame)
        if status.stalling:
            self._send(Alert.stalling(status), frame)

        if status.changed:
            if status.stuck:
                self._nagging.mark(now)
            self._send(
                Alert.for_event(status.event, urgent_states=self._settings.urgent_states),
                frame,
            )
            return

        if status.stuck:
            if self._nagging.due(now):
                self._nagging.mark(now)
                self._send(Alert.still_stuck(status), frame)
            return

        if status.travelling and self._worth_a_heartbeat(status, now):
            self._send(Alert.heartbeat(status), frame)

    def _worth_a_heartbeat(self, status: Status, now: float) -> bool:
        """Due by the clock, and only after real ground has been covered.

        A heartbeat every minute would otherwise repeat the same number while
        the route crawls or the boat sits still.
        """
        if not self._heartbeat.due(now):
            return False
        if status.distance_m is None:
            return False

        covered = (
            self._settings.heartbeat_min_progress_m
            if self._last_heartbeat_distance is None
            else self._last_heartbeat_distance - status.distance_m
        )
        if covered < self._settings.heartbeat_min_progress_m:
            return False

        self._heartbeat.mark(now)
        self._last_heartbeat_distance = status.distance_m
        return True

    def _nothing_to_see(self, reason: str, *, minimised: bool = False) -> None:
        status = self._voyage.update(None, time.monotonic())
        if not status.changed:
            return
        label = "Game minimised" if minimised else "Error"
        self._send(
            Alert.for_event(
                status.event,
                urgent_states=self._settings.urgent_states,
                details={label: reason[:200]},
            ),
            frame=None,
        )

    def _send(self, alert: Alert, frame: Image.Image | None) -> None:
        if self._settings.attach_screenshot:
            alert = alert.showing(frame)
        if self._discord.deliver(alert):
            log.info("Alert sent: %s", alert.headline)

    def _marker_for(self, size: tuple[int, int]) -> Marker:
        if self._marker is None or self._marker_size != size:
            self._marker = build_marker(self._settings, self._calibration, size)
            self._marker_size = size
        return self._marker

    def _report(self, status: Status, observation: Observation) -> None:
        distance = f"{status.distance_m:.0f}m" if status.distance_m is not None else "unknown"
        eta = duration(status.eta_seconds) if status.eta_seconds else "-"
        detail = ""
        if status.distance_m is None:
            detail = f"  match={observation.confidence:.2f} raw={observation.raw_text!r}"
        if observation.near_indicator:
            detail += "  [readout is red]"
        log.info(
            "%-12s distance=%-9s eta=%-9s stalled=%s%s",
            status.state.value,
            distance,
            eta,
            duration(status.stalled_seconds),
            detail,
        )

    def _save_crop(self, observation: Observation) -> None:
        if not self._settings.save_crops or self._debug_dir is None:
            return
        if not observation.readable or observation.sighting is None:
            return
        self._debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        observation.sighting.digits.crop(observation.frame).save(
            self._debug_dir / f"crop-{stamp}.png"
        )

    def _warn_once_if_blank(self, frame: Image.Image) -> None:
        if not blank(frame):
            self._warned_blank = False
            return
        if not self._warned_blank:
            log.error(
                "Captured frame is entirely black. Switch Black Desert to "
                "Borderless Windowed under Settings > Display."
            )
            self._warned_blank = True

    def _tidy_up(self) -> None:
        removed = sum(expire(d, self._settings.retain_days) for d in self._working_dirs)
        if removed:
            log.info(
                "Removed %d working file(s) older than %d days.",
                removed,
                self._settings.retain_days,
            )
        if self._settings.samples_enabled:
            held = ", ".join(f"{k}={v}" for k, v in self._archive.counts().items())
            log.info("Training samples held: %s", held or "none")


def build_marker(settings: Settings, calibration: Calibration, size: tuple[int, int]) -> Marker:
    from .settings import ROOT

    icon = Image.open(ROOT / calibration.icon_path).convert("RGB")
    scale = calibration.scale_for(*size)
    if abs(scale - 1.0) > 0.01:
        log.info(
            "Resolution differs from calibration (%dx%d -> %dx%d); scaling by %.3f.",
            calibration.width,
            calibration.height,
            size[0],
            size[1],
            scale,
        )
    return Marker(
        icon, calibration.offset, match_threshold=settings.match_threshold, scale=scale
    )


def build_readout(settings: Settings) -> Readout:
    from .readout import engine_for

    return Readout(
        engine_for(settings.ocr_backend),
        upscale=settings.upscale,
        brightness_threshold=settings.brightness_threshold,
        floor_m=settings.floor_m,
        ceiling_m=settings.ceiling_m,
    )


def build_voyage(settings: Settings) -> Voyage:
    return Voyage(
        arrival_threshold_m=settings.arrival_threshold_m,
        movement_epsilon_m=settings.movement_epsilon_m,
        stuck_after_seconds=settings.stuck_after_seconds,
        missing_confirm_polls=settings.missing_confirm_polls,
        near_arrival_m=settings.near_arrival_m,
        arrival_confirm_polls=settings.arrival_confirm_polls,
        approaching_m=settings.approaching_m,
        stalling_after_seconds=settings.stalling_after_seconds,
    )
