"""Retention of working files, and the curated training archive."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PIL import Image

from bdo_tracker.storage import (
    LOW_CONF,
    NO_MARKER,
    OK,
    RED,
    UNPARSED,
    SampleArchive,
    prune_directory,
)

DAY = 86400


def make_image(size=(40, 16)) -> Image.Image:
    return Image.new("RGB", size, (30, 30, 40))


def touch(path: Path, age_days: float, now: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = now - age_days * DAY
    import os

    os.utime(path, (stamp, stamp))
    return path


# -- pruning -------------------------------------------------------------


def test_prunes_only_files_past_the_cutoff(tmp_path: Path) -> None:
    now = time.time()
    old = touch(tmp_path / "old.png", age_days=9, now=now)
    fresh = touch(tmp_path / "fresh.png", age_days=1, now=now)

    assert prune_directory(tmp_path, 7, now=now) == 1
    assert not old.exists()
    assert fresh.exists()


def test_pruning_recurses_into_subdirectories(tmp_path: Path) -> None:
    now = time.time()
    nested = touch(tmp_path / "sub" / "deep.png", age_days=30, now=now)
    assert prune_directory(tmp_path, 7, now=now) == 1
    assert not nested.exists()
    assert (tmp_path / "sub").is_dir()  # directories survive


def test_retain_days_of_zero_disables_pruning(tmp_path: Path) -> None:
    now = time.time()
    ancient = touch(tmp_path / "ancient.png", age_days=999, now=now)
    assert prune_directory(tmp_path, 0, now=now) == 0
    assert ancient.exists()


def test_pruning_a_missing_directory_is_harmless(tmp_path: Path) -> None:
    assert prune_directory(tmp_path / "nope", 7) == 0


# -- classification ------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Ordered by training value: the worst outcome wins the label.
        ({"found": False, "parsed": False, "red": False, "confidence": 0.0}, NO_MARKER),
        ({"found": True, "parsed": False, "red": False, "confidence": 0.99}, UNPARSED),
        ({"found": True, "parsed": True, "red": False, "confidence": 0.86}, LOW_CONF),
        ({"found": True, "parsed": True, "red": True, "confidence": 0.99}, RED),
        ({"found": True, "parsed": True, "red": False, "confidence": 0.99}, OK),
    ],
)
def test_classification(kwargs: dict, expected: str) -> None:
    assert SampleArchive.classify(match_threshold=0.85, **kwargs) == expected


def test_a_failure_outranks_a_low_confidence_label() -> None:
    """An unreadable crop is worth more than a merely marginal match."""
    assert (
        SampleArchive.classify(
            found=True, parsed=False, red=False, confidence=0.86, match_threshold=0.85
        )
        == UNPARSED
    )


# -- sampling policy -----------------------------------------------------


def test_anomalies_are_always_kept(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path, min_interval_seconds=9999)
    for category in (UNPARSED, NO_MARKER, LOW_CONF, RED):
        assert archive.should_keep(category, now=0.0)
        assert archive.should_keep(category, now=1.0)


def test_ordinary_reads_are_rate_limited(tmp_path: Path) -> None:
    """A thousand clean reads of the same number teach a model nothing."""
    archive = SampleArchive(tmp_path, min_interval_seconds=1800)
    assert archive.record(OK, make_image(), {}, now=0.0) is not None
    assert archive.record(OK, make_image(), {}, now=60.0) is None      # too soon
    assert archive.record(OK, make_image(), {}, now=1801.0) is not None


def test_rate_limit_does_not_hold_back_anomalies(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path, min_interval_seconds=1800)
    archive.record(OK, make_image(), {}, now=0.0)
    assert archive.record(UNPARSED, make_image(), {}, now=1.0) is not None
    assert archive.record(RED, make_image(), {}, now=2.0) is not None


def test_disabled_archive_writes_nothing(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path, enabled=False)
    assert archive.record(UNPARSED, make_image(), {}) is None
    assert not any(tmp_path.iterdir())


# -- storage -------------------------------------------------------------


def test_sample_is_written_with_its_metadata(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path)
    path = archive.record(
        UNPARSED, make_image(), {"raw_ocr": "11'69 9", "meters": None}, stamp="s1"
    )
    assert path is not None and path.exists()

    payload = json.loads((tmp_path / UNPARSED / "s1.json").read_text(encoding="utf-8"))
    assert payload["raw_ocr"] == "11'69 9"
    assert payload["category"] == UNPARSED
    assert "recorded_at" in payload


def test_per_category_cap_evicts_the_oldest(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path, max_per_category=3)
    for i in range(6):
        archive.record(UNPARSED, make_image(), {"i": i}, stamp=f"s{i}")
        time.sleep(0.01)  # keep mtimes distinct so ordering is well defined

    kept = sorted(p.stem for p in (tmp_path / UNPARSED).glob("*.png"))
    assert len(kept) == 3
    assert kept == ["s3", "s4", "s5"]
    # Sidecars go with their images.
    assert not (tmp_path / UNPARSED / "s0.json").exists()


def test_categories_are_capped_independently(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path, max_per_category=2)
    for i in range(3):
        archive.record(UNPARSED, make_image(), {}, stamp=f"u{i}")
        archive.record(RED, make_image(), {}, stamp=f"r{i}")
    counts = archive.counts()
    assert counts[UNPARSED] == 2
    assert counts[RED] == 2


def test_no_marker_samples_are_downscaled(tmp_path: Path) -> None:
    """A whole-frame sample would otherwise be several megabytes."""
    archive = SampleArchive(tmp_path)
    archive.record(NO_MARKER, make_image((3440, 1440)), {}, stamp="frame")
    with Image.open(tmp_path / NO_MARKER / "frame.png") as img:
        assert img.width <= 960


def test_crops_are_not_downscaled(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path)
    archive.record(UNPARSED, make_image((83, 14)), {}, stamp="crop")
    with Image.open(tmp_path / UNPARSED / "crop.png") as img:
        assert img.size == (83, 14)


def test_counts_reports_zero_for_empty_categories(tmp_path: Path) -> None:
    archive = SampleArchive(tmp_path)
    assert archive.counts()[OK] == 0


def test_samples_survive_pruning(tmp_path: Path) -> None:
    """The archive is curated and permanent; only working files expire."""
    now = time.time()
    samples = tmp_path / "samples"
    captures = tmp_path / "captures"
    old_sample = touch(samples / UNPARSED / "ancient.png", age_days=400, now=now)
    old_capture = touch(captures / "frame.png", age_days=400, now=now)

    # Only the working directory is ever handed to prune_directory.
    prune_directory(captures, 7, now=now)
    assert not old_capture.exists()
    assert old_sample.exists()
