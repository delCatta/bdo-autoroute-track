"""Disk housekeeping, and a curated archive of samples for later training.

Working files expire. The archive does not, being small, labelled, and biased
towards failures, because a thousand clean reads of "600" teach a model nothing
while one misread of 1169 as "9" teaches it a lot.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from .observation import CATEGORIES, NO_MARKER, ORDINARY, Observation

log = logging.getLogger(__name__)

ALWAYS_KEEP = frozenset(category for category in CATEGORIES if category != ORDINARY)
FRAME_SAMPLE_MAX_WIDTH = 960
SECONDS_PER_DAY = 86400


def expire(directory: Path, older_than_days: int, *, now: float | None = None) -> int:
    """Delete files older than `older_than_days`, returning how many went.

    Zero days disables expiry. Directories are left alone.
    """
    if older_than_days <= 0 or not directory.is_dir():
        return 0

    cutoff = (now if now is not None else time.time()) - older_than_days * SECONDS_PER_DAY
    removed = 0
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            log.debug("Could not remove %s: %s", path, exc)
    return removed


@dataclass
class Archive:
    """Labelled samples kept for later training, capped per category."""

    root: Path
    max_per_category: int = 200
    min_interval_seconds: float = 1800.0
    enabled: bool = True
    # A whole-frame sample carries whatever was on screen, so it follows the
    # same policy as an alert screenshot. None keeps it as captured.
    keeps_full_frames: bool = True
    full_frame_width: int | None = None

    def __post_init__(self) -> None:
        self._last_ordinary_at: float | None = None

    def wants(self, category: str, *, now: float | None = None) -> bool:
        """Anomalies always; ordinary successes only once an interval."""
        if not self.enabled:
            return False
        if category in ALWAYS_KEEP or self._last_ordinary_at is None:
            return True
        moment = now if now is not None else time.monotonic()
        return moment - self._last_ordinary_at >= self.min_interval_seconds

    def keep(
        self,
        observation: Observation,
        *,
        match_threshold: float,
        extra: dict[str, object] | None = None,
        now: float | None = None,
        stamp: str | None = None,
    ) -> Path | None:
        if not self.enabled:
            return None
        if observation.borrowed:
            # Something was covering the game, so this frame is somebody's
            # desktop. Worthless as a training negative for template matching,
            # and it would sit here permanently. Keeping it out of Discord while
            # writing it to disk forever would be the wrong half of the fix.
            log.debug("Not archiving a frame captured while the game was covered.")
            return None

        category = observation.category(match_threshold)
        image = observation.sample(category)
        if observation.is_whole_frame(category):
            if not self.keeps_full_frames:
                return None
            image = self._within_policy(image)

        metadata = observation.as_metadata(match_threshold)
        metadata.update(extra or {})
        return self.record(category, image, metadata, now=now, stamp=stamp)

    def _within_policy(self, image: Image.Image) -> Image.Image:
        """A whole frame, shrunk to whatever the screenshot policy allows."""
        width = self.full_frame_width
        if width is None or image.width <= width:
            return image
        height = max(1, round(image.height * width / image.width))
        return image.resize((width, height), Image.LANCZOS)

    def record(
        self,
        category: str,
        image: Image.Image,
        metadata: dict[str, object],
        *,
        now: float | None = None,
        stamp: str | None = None,
    ) -> Path | None:
        """Save one labelled sample, or None when its bucket is satisfied."""
        if not self.wants(category, now=now):
            return None
        if category == ORDINARY:
            self._last_ordinary_at = now if now is not None else time.monotonic()

        directory = self.root / category
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Could not create %s: %s", directory, exc)
            return None

        name = stamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = directory / f"{name}.png"
        if not self._write(path, self._sized(category, image), metadata, category):
            return None
        self._evict_oldest(directory)
        return path

    def counts(self) -> dict[str, int]:
        return {category: len(self._images_in(category)) for category in CATEGORIES}

    @staticmethod
    def _sized(category: str, image: Image.Image) -> Image.Image:
        if category != NO_MARKER or image.width <= FRAME_SAMPLE_MAX_WIDTH:
            return image
        ratio = FRAME_SAMPLE_MAX_WIDTH / image.width
        return image.resize(
            (FRAME_SAMPLE_MAX_WIDTH, max(1, round(image.height * ratio))), Image.LANCZOS
        )

    @staticmethod
    def _write(
        path: Path, image: Image.Image, metadata: dict[str, object], category: str
    ) -> bool:
        try:
            image.save(path)
            payload = dict(metadata)
            payload.setdefault("category", category)
            payload.setdefault("recorded_at", datetime.now().isoformat(timespec="seconds"))
            path.with_suffix(".json").write_text(
                json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
            )
            return True
        except OSError as exc:
            log.warning("Could not write %s: %s", path, exc)
            return False

    def _evict_oldest(self, directory: Path) -> None:
        images = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
        for path in images[: max(0, len(images) - self.max_per_category)]:
            try:
                path.unlink()
                path.with_suffix(".json").unlink(missing_ok=True)
            except OSError as exc:
                log.debug("Could not evict %s: %s", path, exc)

    def _images_in(self, category: str) -> list[Path]:
        directory = self.root / category
        return list(directory.glob("*.png")) if directory.is_dir() else []
