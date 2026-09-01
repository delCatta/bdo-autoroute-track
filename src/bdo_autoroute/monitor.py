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
from .outbox import Outbox
from .marker import Marker, MarkerError
from .observation import Observation
from .readout import Readout
from .settings import MARKER_CROP_MARGIN, Calibration, Settings
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
        outbox: Outbox,
        voyage: Voyage,
        *,
        working_dirs: tuple[Path, ...] = (),
        samples_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._calibration = calibration
        self._readout = readout
        self._outbox = outbox
        self._voyage = voyage
        self._working_dirs = working_dirs
        self._debug_dir = working_dirs[-1] if working_dirs else None

        self._marker: Marker | None = None
        self._marker_size: tuple[int, int] | None = None
        self._stopping = False
        self._warned_blank = False
        self._observers: list = []
        self.paused = False
        self._misses = 0
        self._blamed_resolution = False
        self._config: Path | None = None
        self._config_seen: float | None = None
        self._reloader = None
        self._heartbeat = Timer(settings.heartbeat_seconds)
        self._last_heartbeat_distance: float | None = None
        self._greeted = False
        self._blamed_cover = False
        self._nagging = Timer(settings.stuck_realert_seconds)
        self._archive = Archive(
            root=samples_dir or Path("samples"),
            max_per_category=settings.samples_max_per_category,
            min_interval_seconds=settings.sample_interval_seconds,
            enabled=settings.samples_enabled,
            keeps_full_frames=settings.keeps_full_frame_samples,
            full_frame_width=settings.sample_frame_width,
        )

    def run(self, *, once: bool = False, handle_signals: bool = True) -> int:
        if handle_signals:
            # Only the main thread may install handlers; the tray runs this in
            # a worker and stops it through halt() instead.
            signal.signal(signal.SIGINT, self._on_interrupt)
        self._tidy_up()
        log.info(
            "Watching every %ds via %s. Heartbeat %s. Ctrl+C to stop.",
            self._settings.poll_interval_seconds,
            ", ".join(self._outbox.names) or "nothing",
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

    @property
    def outbox(self) -> Outbox:
        return self._outbox

    def reloads_from(self, path: Path, loader) -> None:
        """Watch a config file and adopt it whenever it changes on disk.

        Saving from anywhere reaches a running monitor this way (the settings
        window, an editor, another process), so nothing has to be restarted and
        nothing has to be told to restart.
        """
        self._config = path
        self._config_seen = self._stamp()
        self._reloader = loader

    def _stamp(self) -> float | None:
        try:
            return self._config.stat().st_mtime if self._config else None
        except OSError:
            return None

    def _reload_if_changed(self) -> None:
        if self._config is None or self._reloader is None:
            return
        stamp = self._stamp()
        if stamp is None or stamp == self._config_seen:
            return

        self._config_seen = stamp
        try:
            settings, outbox = self._reloader()
        except Exception as exc:
            log.error("%s changed but could not be loaded: %s", self._config.name, exc)
            return
        log.info("%s changed on disk.", self._config.name)
        self.apply(settings, outbox)

    def apply(self, settings: Settings, outbox: Outbox) -> None:
        """Adopt new settings mid-run. Nothing is restarted.

        The poll interval, screenshot policy and thresholds are all read fresh
        each poll, so swapping them is enough. The marker is dropped so it is
        rebuilt at the new match threshold.
        """
        self._settings = settings
        self._outbox = outbox
        self._readout = build_readout(settings)
        self._marker = None
        self._marker_size = None
        self._heartbeat.interval = settings.heartbeat_seconds
        self._nagging.interval = settings.stuck_realert_seconds
        self._archive.max_per_category = settings.samples_max_per_category
        self._archive.min_interval_seconds = settings.sample_interval_seconds
        self._archive.enabled = settings.samples_enabled
        self._archive.keeps_full_frames = settings.keeps_full_frame_samples
        self._archive.full_frame_width = settings.sample_frame_width
        self._voyage.retune(
            arrival_threshold_m=settings.arrival_threshold_m,
            movement_epsilon_m=settings.movement_epsilon_m,
            stuck_after_seconds=settings.stuck_after_seconds,
            missing_confirm_polls=settings.missing_confirm_polls,
            near_arrival_m=settings.near_arrival_m,
            arrival_confirm_polls=settings.arrival_confirm_polls,
            approaching_m=settings.approaching_m,
            stalling_after_seconds=settings.stalling_after_seconds,
        )
        log.info("Settings applied: watching every %ds via %s.",
                 settings.poll_interval_seconds, ", ".join(outbox.names) or "nothing")

    def watch(self, observer) -> None:
        """Call `observer(status)` after every poll. Used by the tray."""
        self._observers.append(observer)

    def halt(self) -> None:
        """Finish the current poll and stop."""
        self._stopping = True

    def _on_interrupt(self, _signum: int, _frame: FrameType | None) -> None:
        log.info("Stop requested; finishing this poll.")
        self.halt()

    def _tick(self, capture) -> None:
        self._reload_if_changed()
        if self.paused:
            return
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
        window = Window.matching(self._settings.title_matches, self._settings.process_matches)
        frame = capture.frame(window)
        observation = self._look(
            frame,
            window.size,
            borrowed=capture.borrows_the_desktop and window.obscured,
        )
        self._archive.keep(observation, match_threshold=self._settings.match_threshold)
        self._save_crop(observation)

        now = time.monotonic()
        status = self._voyage.update(
            observation.distance, now, near_indicator=observation.near_indicator
        )
        self._report(status, observation)
        self._announce(status, self._screenshot_for(observation), now)
        self._tell_observers(status)

    def _look(
        self, frame: Image.Image, size: tuple[int, int], *, borrowed: bool = False
    ) -> Observation:
        self._warn_once_if_blank(frame)
        marker = self._marker_for(size)
        sighting = marker.sighting(frame)
        self._note_miss(sighting is None, size)
        if sighting is None or not sighting.readable:
            return Observation(frame=frame, sighting=sighting, borrowed=borrowed)
        return Observation(
            frame=frame,
            sighting=sighting,
            reading=self._readout.reading(sighting.digits.crop(frame)),
            borrowed=borrowed,
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
            self._send(self._heartbeat_for(status), frame)

    def _heartbeat_for(self, status: Status) -> Alert:
        """The first one says it is watching; later ones report progress."""
        if self._greeted:
            return Alert.heartbeat(status)
        self._greeted = True
        return Alert.watching(status)

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

    def _note_miss(self, missed: bool, size: tuple[int, int]) -> None:
        """Blame a changed resolution once it is the obvious explanation.

        A template scaled to a different resolution can score 0.00 and simply
        report "marker not found" forever, with nothing pointing at the cause.
        """
        if not missed:
            self._misses = 0
            return

        self._misses += 1
        scale = self._calibration.scale_for(*size)
        if self._blamed_resolution or abs(scale - 1.0) <= 0.01:
            return
        if self._misses < self._settings.missing_confirm_polls:
            return

        self._blamed_resolution = True
        log.error(
            "The marker has not been found in %d polls, and the game is at "
            "%dx%d while the calibration was made at %dx%d. Template matching "
            "does not survive that. Re-run calibrate.cmd at this resolution.",
            self._misses,
            size[0],
            size[1],
            self._calibration.width,
            self._calibration.height,
        )

    def _screenshot_for(self, observation: Observation) -> Image.Image | None:
        """As much of the screen as the settings permit, and no more."""
        if not self._settings.wants_screenshot:
            return None
        if observation.borrowed:
            self._warn_once_about_cover()
            return None
        if self._settings.crops_screenshot:
            return observation.neighbourhood(MARKER_CROP_MARGIN)
        return observation.frame

    def _warn_once_about_cover(self) -> None:
        if self._blamed_cover:
            return
        self._blamed_cover = True
        log.warning(
            "Something is covering the game and capture is reading the desktop, "
            "so alerts will carry no screenshot until it is uncovered. Set "
            'capture.method = "window" to read the game window directly.'
        )

    def _tell_observers(self, status: Status) -> None:
        for observer in self._observers:
            try:
                observer(status)
            except Exception as exc:
                log.debug("Observer failed: %s", exc)

    def _nothing_to_see(self, reason: str, *, minimised: bool = False) -> None:
        status = self._voyage.update(None, time.monotonic())
        self._tell_observers(status)
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
        alert = alert.showing(frame)
        if self._outbox.deliver(alert):
            log.info("Alert sent: %s", alert.headline)

    def _marker_for(self, size: tuple[int, int]) -> Marker:
        if self._marker is None or self._marker_size != size:
            self._marker = build_marker(self._settings, self._calibration, size)
            self._marker_size = size
        return self._marker

    def _report(self, status: Status, observation: Observation) -> None:
        distance = f"{status.distance_m:.0f}m" if status.distance_m is not None else "unknown"
        eta = duration(status.eta_seconds) if status.eta_seconds else "-"
        # A poll that read nothing still reports the last known distance, and
        # without this it looks exactly like a fresh measurement. Repeated
        # identical lines were being read as "not moving" when the truth was
        # "not seen".
        detail = ""
        if not status.fresh:
            # Nothing has ever been read, so there is no last known value to
            # carry over and nothing to qualify.
            if status.distance_m is not None:
                distance += " (last known)"
            detail = f"  match={observation.confidence:.2f} raw={observation.raw_text!r}"
        if observation.near_indicator:
            detail += "  [readout is red]"
        if status.held is not None:
            detail += f"  [HELD {status.held:.0f}m: too far to be real, awaiting confirmation]"
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
