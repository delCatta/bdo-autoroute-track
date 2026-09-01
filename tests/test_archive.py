"""Archive: expiring working files, keeping a curated sample set."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from PIL import Image

from bdo_autoroute.archive import Archive, expire
from bdo_autoroute.marker import Box, Sighting
from bdo_autoroute.observation import NO_MARKER, ORDINARY, RED, UNPARSED, Observation
from bdo_autoroute.readout import Reading

DAY = 86400
MISREAD_TEXT = "11" + chr(39) + "69 9"


def image(size=(40, 16)) -> Image.Image:
    return Image.new("RGB", size, (30, 30, 40))


def aged(path: Path, days: float, now: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = now - days * DAY
    os.utime(path, (stamp, stamp))
    return path


class TestExpire:
    def test_expire_removes_only_files_past_the_cutoff(self, tmp_path):
        now = time.time()
        old = aged(tmp_path / "old.png", 9, now)
        fresh = aged(tmp_path / "fresh.png", 1, now)

        assert expire(tmp_path, 7, now=now) == 1
        assert not old.exists()
        assert fresh.exists()

    def test_expire_reaches_into_subdirectories(self, tmp_path):
        now = time.time()
        nested = aged(tmp_path / "sub" / "deep.png", 30, now)
        assert expire(tmp_path, 7, now=now) == 1
        assert not nested.exists()
        assert (tmp_path / "sub").is_dir()

    def test_expire_does_nothing_when_disabled(self, tmp_path):
        now = time.time()
        ancient = aged(tmp_path / "ancient.png", 999, now)
        assert expire(tmp_path, 0, now=now) == 0
        assert ancient.exists()

    def test_expire_tolerates_a_missing_directory(self, tmp_path):
        assert expire(tmp_path / "nope", 7) == 0


class TestWants:
    @pytest.mark.parametrize("category", [UNPARSED, NO_MARKER, RED])
    def test_wants_is_always_true_for_anomalies(self, tmp_path, category):
        archive = Archive(tmp_path, min_interval_seconds=9999)
        assert archive.wants(category, now=0.0)
        assert archive.wants(category, now=1.0)

    def test_wants_throttles_ordinary_successes(self, tmp_path):
        archive = Archive(tmp_path, min_interval_seconds=1800)
        assert archive.record(ORDINARY, image(), {}, now=0.0) is not None
        assert archive.record(ORDINARY, image(), {}, now=60.0) is None
        assert archive.record(ORDINARY, image(), {}, now=1801.0) is not None

    def test_wants_is_false_when_the_archive_is_disabled(self, tmp_path):
        archive = Archive(tmp_path, enabled=False)
        assert archive.record(UNPARSED, image(), {}) is None
        assert not any(tmp_path.iterdir())


class TestRecord:
    def test_record_writes_the_image_and_its_metadata(self, tmp_path):
        archive = Archive(tmp_path)
        path = archive.record(UNPARSED, image(), {"raw_ocr": MISREAD_TEXT}, stamp="s1")
        assert path.exists()

        sidecar = json.loads((tmp_path / UNPARSED / "s1.json").read_text(encoding="utf-8"))
        assert sidecar["raw_ocr"] == MISREAD_TEXT
        assert sidecar["category"] == UNPARSED
        assert "recorded_at" in sidecar

    def test_record_evicts_the_oldest_once_a_category_is_full(self, tmp_path):
        archive = Archive(tmp_path, max_per_category=3)
        for index in range(6):
            archive.record(UNPARSED, image(), {"i": index}, stamp=f"s{index}")
            time.sleep(0.01)

        kept = sorted(p.stem for p in (tmp_path / UNPARSED).glob("*.png"))
        assert kept == ["s3", "s4", "s5"]
        assert not (tmp_path / UNPARSED / "s0.json").exists()

    def test_record_caps_each_category_separately(self, tmp_path):
        archive = Archive(tmp_path, max_per_category=2)
        for index in range(3):
            archive.record(UNPARSED, image(), {}, stamp=f"u{index}")
            archive.record(RED, image(), {}, stamp=f"r{index}")
        assert archive.counts()[UNPARSED] == 2
        assert archive.counts()[RED] == 2

    def test_record_shrinks_whole_frame_samples(self, tmp_path):
        Archive(tmp_path).record(NO_MARKER, image((3440, 1440)), {}, stamp="frame")
        with Image.open(tmp_path / NO_MARKER / "frame.png") as saved:
            assert saved.width <= 960

    def test_record_keeps_crops_at_their_original_size(self, tmp_path):
        Archive(tmp_path).record(UNPARSED, image((83, 14)), {}, stamp="crop")
        with Image.open(tmp_path / UNPARSED / "crop.png") as saved:
            assert saved.size == (83, 14)


class TestKeep:
    def test_keep_labels_and_stores_an_observation(self, tmp_path):
        archive = Archive(tmp_path)
        observation = Observation(
            Image.new("RGB", (200, 100)),
            Sighting(0.99, Box(80, 10, 17, 16), Box(10, 10, 60, 14)),
            Reading(500.0, "500"),
        )
        path = archive.keep(observation, match_threshold=0.85, stamp="obs")

        assert path.parent.name == ORDINARY
        sidecar = json.loads((tmp_path / ORDINARY / "obs.json").read_text(encoding="utf-8"))
        assert sidecar["meters"] == 500.0

    def test_keep_merges_extra_metadata(self, tmp_path):
        archive = Archive(tmp_path)
        archive.keep(
            Observation(Image.new("RGB", (60, 30))),
            match_threshold=0.85,
            extra={"note": "camera away"},
            stamp="obs",
        )
        sidecar = json.loads((tmp_path / NO_MARKER / "obs.json").read_text(encoding="utf-8"))
        assert sidecar["note"] == "camera away"


class TestCounts:
    def test_counts_reports_zero_for_untouched_categories(self, tmp_path):
        assert Archive(tmp_path).counts()[ORDINARY] == 0
