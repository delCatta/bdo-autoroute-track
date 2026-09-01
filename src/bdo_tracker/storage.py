"""Disk housekeeping: expire old captures, and keep a curated training archive.

Two jobs, deliberately separate:

  prune_directory   Working files (captures/, debug/) are transient. They expire
                    after storage.retain_days so a monitor left running for
                    weeks does not fill the disk.

  SampleArchive     A small, permanent, curated set under samples/, exempt from
                    pruning. Sampling is biased towards FAILURES, because a
                    thousand clean reads of "600" teach a future model nothing
                    while one misread of 1169 as "9" teaches it a lot. Routine
                    successes are rate-limited to a trickle; anomalies are
                    always kept, up to a per-category cap.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)


class Category(str):
    """Sample buckets. Plain strings so they read well as directory names."""


# Ordered by training value, most valuable first.
UNPARSED = "unparsed"      # OCR ran but produced no number: the richest failures
NO_MARKER = "no_marker"    # the marker was not found at all: negative examples
LOW_CONF = "low_conf"      # marker matched only just above threshold
RED = "red"                # near-arrival red text: rare, and easy to get wrong
OK = "ok"                  # ordinary successful reads, heavily rate-limited

ALL_CATEGORIES = (UNPARSED, NO_MARKER, LOW_CONF, RED, OK)

# Anomalous categories are always worth keeping; OK is throttled.
_ALWAYS_KEEP = frozenset({UNPARSED, NO_MARKER, LOW_CONF, RED})

# A no_marker sample is a whole frame, so store it small.
_FRAME_SAMPLE_MAX_WIDTH = 960


def prune_directory(directory: Path, max_age_days: int, *, now: float | None = None) -> int:
    """Delete files under `directory` older than `max_age_days`. Returns the count.

    `max_age_days` of 0 disables pruning, so a user can opt out by setting it.
    Directories are left alone; only files are removed.
    """
    if max_age_days <= 0 or not directory.is_dir():
        return 0

    cutoff = (now if now is not None else time.time()) - max_age_days * 86400
    removed = 0
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:  # a locked or vanished file must not stop the sweep
            log.debug("Could not remove %s: %s", path, exc)
    return removed


@dataclass
class SampleArchive:
    """Keeps a bounded, curated set of labelled samples for later training.

    Each sample is an image plus a JSON sidecar of everything known about it at
    capture time, so it can be re-labelled later without guessing.
    """

    root: Path
    max_per_category: int = 200
    min_interval_seconds: float = 1800.0
    enabled: bool = True

    def __post_init__(self) -> None:
        self._last_ok_at: float | None = None

    # -- classification --------------------------------------------------

    @staticmethod
    def classify(
        *,
        found: bool,
        parsed: bool,
        red: bool,
        confidence: float,
        match_threshold: float,
        low_conf_margin: float = 0.05,
    ) -> str:
        """Pick the bucket for one poll's outcome, most valuable label winning."""
        if not found:
            return NO_MARKER
        if not parsed:
            return UNPARSED
        if confidence < match_threshold + low_conf_margin:
            return LOW_CONF
        if red:
            return RED
        return OK

    def should_keep(self, category: str, *, now: float | None = None) -> bool:
        """Anomalies always; ordinary successes only every min_interval_seconds."""
        if not self.enabled:
            return False
        if category in _ALWAYS_KEEP:
            return True
        moment = now if now is not None else time.monotonic()
        if self._last_ok_at is None:
            return True
        return moment - self._last_ok_at >= self.min_interval_seconds

    # -- writing ---------------------------------------------------------

    def record(
        self,
        category: str,
        image: Image.Image,
        metadata: dict[str, object],
        *,
        now: float | None = None,
        stamp: str | None = None,
    ) -> Path | None:
        """Save one labelled sample. Returns its path, or None if it was skipped."""
        if not self.should_keep(category, now=now):
            return None
        if category == OK:
            self._last_ok_at = now if now is not None else time.monotonic()

        directory = self.root / category
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Could not create sample directory %s: %s", directory, exc)
            return None

        if category == NO_MARKER and image.width > _FRAME_SAMPLE_MAX_WIDTH:
            ratio = _FRAME_SAMPLE_MAX_WIDTH / image.width
            image = image.resize(
                (_FRAME_SAMPLE_MAX_WIDTH, max(1, round(image.height * ratio))), Image.LANCZOS
            )

        name = stamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        image_path = directory / f"{name}.png"
        try:
            image.save(image_path)
            payload = dict(metadata)
            payload.setdefault("category", category)
            payload.setdefault("recorded_at", datetime.now().isoformat(timespec="seconds"))
            (directory / f"{name}.json").write_text(
                json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            log.warning("Could not write sample %s: %s", image_path, exc)
            return None

        self._enforce_cap(directory)
        return image_path

    def _enforce_cap(self, directory: Path) -> None:
        """Drop the oldest samples once a category is over its cap."""
        images = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
        excess = len(images) - self.max_per_category
        for path in images[:max(0, excess)]:
            try:
                path.unlink()
                path.with_suffix(".json").unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - best effort
                log.debug("Could not evict %s: %s", path, exc)

    def counts(self) -> dict[str, int]:
        """How many samples are held per category."""
        return {
            category: len(list((self.root / category).glob("*.png")))
            if (self.root / category).is_dir()
            else 0
            for category in ALL_CATEGORIES
        }
