"""A report you can attach to an issue without publishing your own secrets.

CONTRIBUTING asks people to send a log and some samples, because that is the
only way the OCR misreads get fixed. Following that instruction by hand is not
safe:

- the log carried the live webhook token on every delivery failure until 0.3.1,
  and a webhook URL is a bearer credential
- `-v`, which the same instructions recommend for chasing a misread, writes
  every visible window title into the log, so document names and browser tabs
- `samples/no_marker/` holds whole window frames, with guild chat, whispers,
  a character name and the marketplace in them

So the bundle is built rather than described. One command, one file, and the
things that should not leave the machine are never put in it.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from .settings import Settings
from .vault import scrubbed

log = logging.getLogger(__name__)

# Categories whose sample is a crop of the digits, roughly 83x14 pixels of a
# number. `no_marker` is deliberately absent: it is a whole window frame by
# nature, because a missing marker only means anything in context.
SAFE_CATEGORIES = ("unparsed", "low_confidence", "red", "ordinary")

# Anything quoted is hidden unless it is the OCR text, which is the whole point
# of sending the log. Listing the phrases that name a window was the first
# attempt and it missed `Found 'BLACK DESERT - 528853' at 3440x1440`, which
# carries a family number. Default deny, one explicit exception.
QUOTED = re.compile(r"(?<!raw=)'[^']*'")
MENTION = re.compile(r"<@!?\d+>")


def safe_line(line: str) -> str:
    """One log line with everything identifying taken out of it.

    Three passes, because they leak differently. A webhook token appears as a
    URL or as a bare path, a window title appears in quotes, and a Discord
    mention is a user id.
    """
    line = scrubbed(line)
    line = QUOTED.sub("'(hidden)'", line)
    return MENTION.sub("<@user hidden>", line)


class Bundle:
    """Everything needed to diagnose a misread, and nothing that identifies you."""

    def __init__(self, root: Path, settings: Settings) -> None:
        self._root = root
        self._settings = settings

    def write(self, destination: Path | None = None) -> Path:
        """Build the zip and return where it landed."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = destination or self._root / "reports" / f"autoroute-report-{stamp}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.txt", self.summary())
            self._add_log(archive)
            self._add_samples(archive)
            self._add_calibration(archive)
        return target

    # -- what goes in ----------------------------------------------------

    def summary(self) -> str:
        """The context an issue needs, with no webhook anywhere in it."""
        settings = self._settings
        lines = [
            "bdo-autoroute-track report",
            f"generated     {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            f"version       {_version()}",
            f"python        {sys.version.split()[0]}",
            f"windows       {platform.platform()}",
            "",
            f"capture       {settings.capture_method}",
            f"screenshot    {settings.screenshot}",
            f"channels      {', '.join(settings.channels) or 'none'}",
            f"modes         {settings.notification_modes}",
            f"webhook       {'configured' if settings.webhook_url else 'not set'}",
            "",
            f"match_thresh  {settings.match_threshold}",
            f"brightness    {settings.brightness_threshold}",
            f"upscale       {settings.upscale}",
            f"arrival_m     {settings.arrival_threshold_m}",
            f"stuck_seconds {settings.stuck_after_seconds}",
            "",
            self._calibration_line(),
            "",
            "samples included:",
        ]
        for category in SAFE_CATEGORIES:
            lines.append(f"  {category:16} {len(self._samples(category))}")
        held = len(list((self._root / "samples" / "no_marker").glob("*.png")))
        lines.append(f"  {'no_marker':16} {held} on disk, excluded (whole window frames)")
        return "\n".join(lines) + "\n"

    def _calibration_line(self) -> str:
        path = self._root / "calibration.json"
        if not path.exists():
            return "calibration   not calibrated yet"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return (
                f"calibration   {data.get('client_width')}x{data.get('client_height')}"
                f", offset {data.get('digits_offset')}"
            )
        except Exception as exc:
            return f"calibration   unreadable ({exc})"

    def _add_log(self, archive: zipfile.ZipFile) -> None:
        """Every rotated log, one line at a time, scrubbed on the way through."""
        logs = sorted((self._root / "logs").glob("autoroute.log*"))
        if not logs:
            archive.writestr("logs/README.txt", "No log file. Run with --log to record one.\n")
            return
        for path in logs:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("Could not read %s: %s", path, exc)
                continue
            cleaned = "".join(safe_line(line) for line in text.splitlines(keepends=True))
            archive.writestr(f"logs/{path.name}", cleaned)

    def _add_samples(self, archive: zipfile.ZipFile) -> None:
        for category in SAFE_CATEGORIES:
            for path in self._samples(category):
                archive.write(path, f"samples/{category}/{path.name}")
                sidecar = path.with_suffix(".json")
                if sidecar.exists():
                    archive.write(sidecar, f"samples/{category}/{sidecar.name}")

    def _samples(self, category: str) -> list[Path]:
        return sorted((self._root / "samples" / category).glob("*.png"))

    def _add_calibration(self, archive: zipfile.ZipFile) -> None:
        path = self._root / "calibration.json"
        if path.exists():
            archive.write(path, "calibration.json")


def _version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "unknown"
