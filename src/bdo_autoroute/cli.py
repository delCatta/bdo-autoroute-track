"""Argument parsing and dispatch. Everything else lives on an object."""

from __future__ import annotations

import argparse
import logging
import sys

from . import commands
from .marker import MarkerError
from .readout import OcrError
from .settings import Settings, SettingsError
from .window import CaptureError

log = logging.getLogger("bdo_autoroute")

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


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
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
