"""Argument parsing and dispatch. Everything else lives on an object."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import commands
from .marker import MarkerError
from .readout import OcrError
from .settings import ROOT, Settings, SettingsError
from .window import CaptureError

log = logging.getLogger("bdo_autoroute")

LOGS = ROOT / "logs"
LOG_FILE = LOGS / "autoroute.log"
LOG_BYTES = 2_000_000
LOG_BACKUPS = 5

COMMANDS = {
    "calibrate": commands.calibrate,
    "run": commands.run,
    "shot": commands.shot,
    "test-notify": commands.test_notify,
    "windows": commands.windows,
}


def parser() -> argparse.ArgumentParser:
    parsed = argparse.ArgumentParser(
        prog="bdo-autoroute",
        description=(
            "Watch the Black Desert auto-route distance readout and alert when "
            "you arrive or get stuck."
        ),
    )
    parsed.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    subcommands = parsed.add_subparsers(dest="command", required=True)

    subcommands.add_parser("calibrate", help="box the distance digits and the icon")
    running = subcommands.add_parser("run", help="start watching")
    running.add_argument("--once", action="store_true", help="poll a single time and exit")
    subcommands.add_parser("shot", help="one look, for troubleshooting")
    subcommands.add_parser("test-notify", help="send a test alert to Discord")
    subcommands.add_parser("windows", help="list windows and which ones match")
    return parsed


def start_logging(verbose: bool) -> None:
    """Console for watching, a rotating file for working out what happened later.

    Intermittent misreads are the hard ones, and they are only diagnosable
    against a record. The file keeps full dates where the console keeps clock
    times, and every poll is logged whether or not it produced an alert.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        to_file = RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        to_file.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s")
        )
        root.addHandler(to_file)
    except OSError as exc:
        log.warning("Could not open %s for logging (%s); console only.", LOG_FILE, exc)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    start_logging(args.verbose)
    try:
        return COMMANDS[args.command](Settings.load(), args)
    except (SettingsError, CaptureError, MarkerError, OcrError) as exc:
        log.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        log.info("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
