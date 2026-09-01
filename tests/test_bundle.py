"""The report people attach to public issues.

CONTRIBUTING has always asked for a log and some samples, because that is the
only way an OCR misread ever gets fixed. Following that by hand is not safe, and
the failure is silent and permanent: a public issue cannot be un-published.

Every test here is an invariant about what must never be in the zip. The first
version of this builder failed three of them, and only because the bundle was
opened and inspected rather than trusted:

- the webhook id survived, because the scrubber replaced the token and kept the
  path around it
- `Found 'BLACK DESERT - 528853' at 3440x1440` survived, because the redactor
  listed the phrases that name a window instead of hiding quoted text by default
- the calibration line read `NonexNone`, because it guessed the key names

The last one is only cosmetic. The other two are the whole point of the tool.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from PIL import Image

from bdo_autoroute.bundle import SAFE_CATEGORIES, Bundle, safe_line
from bdo_autoroute.settings import Settings

TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
WEBHOOK_ID = "1111111111111111111"
WEBHOOK = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/{TOKEN}"

LOG = f"""2026-09-01 10:38:34,999  INFO  Found 'BLACK DESERT - 528853' at 3440x1440
2026-09-01 10:39:01,000  WARN  Discord notification failed: 401 for url: {WEBHOOK}
2026-09-01 10:39:02,000  WARN  Max retries with url: /api/webhooks/{WEBHOOK_ID}/{TOKEN}
2026-09-01 10:39:03,000  INFO  TRAVELLING distance=3560m raw='11 020' [HELD 7910m]
2026-09-01 10:39:04,000  DEBUG     hwnd=197122   Discord.exe  '#barter | Black Desert - Sailing'
2026-09-01 10:39:05,000  INFO  Alert sent to <@314911950393835521>
"""


def project(tmp_path: Path) -> Path:
    """A working tree with the shapes the bundler cares about."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "autoroute.log").write_text(LOG, encoding="utf-8")

    for category in SAFE_CATEGORIES:
        folder = tmp_path / "samples" / category
        folder.mkdir(parents=True)
        Image.new("RGB", (83, 14), (0, 0, 0)).save(folder / "a.png")
        (folder / "a.json").write_text(json.dumps({"raw_ocr": "740"}), encoding="utf-8")

    whole = tmp_path / "samples" / "no_marker"
    whole.mkdir(parents=True)
    Image.new("RGB", (960, 402), (30, 30, 40)).save(whole / "frame.png")

    (tmp_path / "calibration.json").write_text(
        json.dumps(
            {
                "digits_offset": [-86, 0, 83, 14],
                "client_width": 3440,
                "client_height": 1440,
                "template_path": "icon_template.png",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config.toml").write_text(
        f'[notify]\ndiscord_webhook_url = "{WEBHOOK}"\n', encoding="utf-8"
    )
    return tmp_path


def built(tmp_path: Path) -> zipfile.ZipFile:
    root = project(tmp_path)
    return zipfile.ZipFile(Bundle(root, Settings()).write())


def text_of(archive: zipfile.ZipFile) -> str:
    return "".join(
        archive.read(name).decode("utf-8", "replace")
        for name in archive.namelist()
        if not name.endswith(".png")
    )


class TestSafeLine:
    def test_a_webhook_url_loses_its_token(self):
        assert TOKEN not in safe_line(f"failed for url: {WEBHOOK}")

    def test_a_webhook_url_loses_its_id_as_well(self):
        """The id names the channel and the server, even without the token."""
        assert WEBHOOK_ID not in safe_line(f"failed for url: {WEBHOOK}")

    def test_a_bare_webhook_path_is_redacted(self):
        line = f"Max retries with url: /api/webhooks/{WEBHOOK_ID}/{TOKEN}"
        assert TOKEN not in safe_line(line)
        assert WEBHOOK_ID not in safe_line(line)

    def test_a_window_title_is_hidden(self):
        assert "BLACK DESERT - 528853" not in safe_line(
            "Found 'BLACK DESERT - 528853' at 3440x1440"
        )

    def test_a_discord_mention_is_hidden(self):
        assert "314911950393835521" not in safe_line("Alert sent to <@314911950393835521>")

    def test_the_ocr_text_is_kept(self):
        """Hiding this would leave nothing worth sending."""
        assert "raw='11 020'" in safe_line("TRAVELLING distance=3560m raw='11 020'")

    def test_the_numbers_around_it_are_kept(self):
        cleaned = safe_line("TRAVELLING distance=3560m raw='11 020' [HELD 7910m]")
        assert "3560m" in cleaned and "HELD 7910m" in cleaned


class TestBundleContents:
    def test_it_carries_the_log(self, tmp_path):
        assert any(n.startswith("logs/") for n in built(tmp_path).namelist())

    def test_it_carries_the_digit_crops(self, tmp_path):
        names = built(tmp_path).namelist()
        for category in SAFE_CATEGORIES:
            assert f"samples/{category}/a.png" in names

    def test_it_carries_the_sidecars(self, tmp_path):
        assert "samples/unparsed/a.json" in built(tmp_path).namelist()

    def test_it_carries_the_calibration(self, tmp_path):
        assert "calibration.json" in built(tmp_path).namelist()

    def test_the_summary_reads_the_calibration_correctly(self, tmp_path):
        summary = built(tmp_path).read("report.txt").decode()
        assert "3440x1440" in summary
        assert "None" not in summary


class TestBundleLeaksNothing:
    """The invariants. Each one is a thing that must never reach a public issue."""

    def test_no_whole_window_frame_is_included(self, tmp_path):
        assert not [n for n in built(tmp_path).namelist() if "no_marker" in n]

    def test_no_included_image_is_bigger_than_a_digit_crop(self, tmp_path):
        archive = built(tmp_path)
        for name in archive.namelist():
            if name.endswith(".png"):
                image = Image.open(io.BytesIO(archive.read(name)))
                assert image.width <= 200, f"{name} is {image.size}"

    def test_the_config_is_never_included(self, tmp_path):
        assert not [n for n in built(tmp_path).namelist() if "config.toml" in n]

    def test_the_token_is_nowhere_in_it(self, tmp_path):
        assert TOKEN not in text_of(built(tmp_path))

    def test_the_webhook_id_is_nowhere_in_it(self, tmp_path):
        assert WEBHOOK_ID not in text_of(built(tmp_path))

    def test_no_window_title_is_in_it(self, tmp_path):
        inside = text_of(built(tmp_path))
        assert "BLACK DESERT - 528853" not in inside
        assert "Black Desert - Sailing" not in inside

    def test_the_summary_never_prints_the_webhook(self, tmp_path):
        root = project(tmp_path)
        summary = Bundle(root, Settings(webhook_url=WEBHOOK)).summary()
        assert TOKEN not in summary
        assert WEBHOOK_ID not in summary
        assert "configured" in summary

    def test_it_says_what_it_left_out(self, tmp_path):
        """Silence about the excluded frames would read as "there were none"."""
        assert "excluded" in built(tmp_path).read("report.txt").decode()


class TestWithoutAnything:
    def test_an_empty_project_still_produces_a_bundle(self, tmp_path):
        archive = zipfile.ZipFile(Bundle(tmp_path, Settings()).write())
        assert "report.txt" in archive.namelist()

    def test_it_says_when_there_is_no_log(self, tmp_path):
        archive = zipfile.ZipFile(Bundle(tmp_path, Settings()).write())
        assert "--log" in archive.read("logs/README.txt").decode()

    def test_it_says_when_there_is_no_calibration(self, tmp_path):
        summary = Bundle(tmp_path, Settings()).summary()
        assert "not calibrated yet" in summary
