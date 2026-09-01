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

# These run before, or instead of, a working config.
CONFIGLESS = {"settings", "protect"}

COMMANDS = {
    "calibrate": commands.calibrate,
    "run": commands.run,
    "tray": commands.tray,
    "shot": commands.shot,
    "test-notify": commands.test_notify,
    "windows": commands.windows,
    "settings": commands.configure,
    "protect": commands.protect,
}


def parser() -> argparse.ArgumentParser:
    # Shared so -v and --log are accepted on either side of the subcommand:
    # `run --log` is what people type, whatever argparse would prefer.
    #
    # SUPPRESS matters here. With an ordinary default the subparser writes its
    # own False over a flag given before the subcommand, so `--log run` would
    # silently do nothing.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="debug logging",
    )
    common.add_argument(
        "--log",
        action="store_true",
        default=argparse.SUPPRESS,
        help="write logs/autoroute.log for this run, whatever the config says",
    )

    parsed = argparse.ArgumentParser(
        prog="bdo-autoroute",
        parents=[common],
        description=(
            "Watch the Black Desert auto-route distance readout and alert when "
            "you arrive or get stuck."
        ),
    )
    subcommands = parsed.add_subparsers(dest="command", required=True)

    subcommands.add_parser("calibrate", parents=[common], help="box the digits and the icon")
    running = subcommands.add_parser("run", parents=[common], help="start watching")
    running.add_argument("--once", action="store_true", help="poll a single time and exit")
    subcommands.add_parser(
        "tray", parents=[common], help="run in the background with a tray icon"
    )
    subcommands.add_parser("shot", parents=[common], help="one look, for troubleshooting")
    subcommands.add_parser("test-notify", parents=[common], help="send a test alert")
    subcommands.add_parser("windows", parents=[common], help="list windows and which match")
    subcommands.add_parser("settings", parents=[common], help="open the settings window")
    subcommands.add_parser(
        "protect", parents=[common], help="encrypt the webhook already in config.toml"
    )
    return parsed


def start_logging(verbose: bool) -> None:
    """Console output, which every run gets."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
    root.addHandler(console)


def also_log_to_file(settings: Settings) -> None:
    """Add the rotating file log. Off unless asked for.

    Intermittent misreads are the hard ones, and they are only diagnosable
    against a record: the file keeps full dates where the console keeps clock
    times, and every poll lands in it whether or not it raised an alert.
    """
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_keep_files,
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Could not open %s (%s); console only.", LOG_FILE, exc)
        return

    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s"))
    logging.getLogger().addHandler(handler)
    log.info("Logging to %s", LOG_FILE)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    start_logging(getattr(args, "verbose", False))
    try:
        if args.command in CONFIGLESS:
            return COMMANDS[args.command](None, args)

        settings = Settings.load()
        if settings.log_to_file or getattr(args, "log", False):
            also_log_to_file(settings)
        return COMMANDS[args.command](settings, args)
    except (SettingsError, CaptureError, MarkerError, OcrError) as exc:
        log.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        log.info("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
