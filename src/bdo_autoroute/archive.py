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
        category = observation.category(match_threshold)
        metadata = observation.as_metadata(match_threshold)
        metadata.update(extra or {})
        return self.record(
            category, observation.sample(category), metadata, now=now, stamp=stamp
        )

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
