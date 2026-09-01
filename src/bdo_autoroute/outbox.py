"""Where alerts go.

A channel is anything that can take an Alert and try to deliver it. Failure is
reported, never raised: one dead channel must not stop the others, and must
certainly not stop the monitor.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from .alerts import Alert

log = logging.getLogger(__name__)

# How many deliveries may fail in a row before it is treated as broken rather
# than unlucky. A monitor that has quietly stopped notifying is the worst
# possible failure: it looks exactly like one with nothing to report.
FAILURES_BEFORE_COMPLAINT = 3

# How much a channel wants to hear. "verbose" takes everything, including the
# heartbeat; "important" takes only what a person would want to be interrupted
# for. Desktop toasts default to important, because a toast every minute
# teaches you to dismiss them without reading.
VERBOSE = "verbose"
IMPORTANT = "important"
MODES = (VERBOSE, IMPORTANT)


@runtime_checkable
class Channel(Protocol):
    name: str

    def deliver(self, alert: Alert) -> bool: ...


class Outbox:
    """Every channel an alert should reach."""

    def __init__(
        self, channels: list[Channel], modes: dict[str, str] | None = None
    ) -> None:
        self._channels = channels
        self._failures: dict[str, int] = {}
        self._silenced: set[str] = set()
        self._modes = dict(modes or {})

    @property
    def names(self) -> list[str]:
        return [c.name for c in self._channels]

    @property
    def speaking(self) -> list[str]:
        """The channels that will actually deliver, which is what to report.

        `names` is every channel that exists; saying "alerting discord and
        desktop" when desktop is switched off is a UI telling a lie.
        """
        return [c.name for c in self._channels if not self.silenced(c.name)]

    @property
    def muted(self) -> bool:
        """Every channel switched off. Derived, so there is one way to be quiet."""
        return bool(self._channels) and all(self.silenced(c.name) for c in self._channels)

    def has(self, name: str) -> bool:
        """Whether a channel exists at all, which Discord does only with a webhook."""
        return name in self.names

    def silenced(self, name: str) -> bool:
        return name in self._silenced

    def mode(self, name: str) -> str:
        return self._modes.get(name, VERBOSE)

    def set_mode(self, name: str, mode: str) -> None:
        self._modes[name] = mode

    def carries(self, name: str, alert: Alert) -> bool:
        """Whether this channel wants this alert at all.

        Separate from `silenced`. A channel that skips the heartbeat has not
        stopped working, so a skip must never count as a delivery failure.
        """
        return not (alert.routine and self.mode(name) == IMPORTANT)

    def silence(self, name: str, quiet: bool = True) -> None:
        """Stop or resume one channel, leaving the rest alone."""
        if quiet:
            self._silenced.add(name)
        else:
            self._silenced.discard(name)
            self._failures[name] = 0

    @property
    def empty(self) -> bool:
        return not self._channels

    def deliver(self, alert: Alert) -> bool:
        """Send to every channel that is switched on. True if any accepted it.

        A silenced channel is skipped before anything is counted, so choosing to
        be quiet is never mistaken for a channel that has stopped working.
        """
        listening = [c for c in self._channels if not self.silenced(c.name)]
        if self._channels and not listening:
            log.info("Every channel is off, so %r was not sent.", alert.headline)
            return False

        speaking = [c for c in listening if self.carries(c.name, alert)]
        if listening and not speaking:
            log.debug(
                "%r is routine and every channel wants important only.", alert.headline
            )
            return False

        delivered = False
        for channel in speaking:
            if self._deliver_one(channel, alert):
                delivered = True

        if speaking and not delivered:
            log.error("Alert %r reached nobody: every channel failed.", alert.headline)
        return delivered

    def _deliver_one(self, channel: Channel, alert: Alert) -> bool:
        try:
            sent = channel.deliver(alert)
        except Exception as exc:
            log.warning("%s raised while delivering: %s", channel.name, exc)
            sent = False

        if sent:
            if self._failures.get(channel.name):
                log.info("%s is delivering again.", channel.name)
            self._failures[channel.name] = 0
            return True

        missed = self._failures.get(channel.name, 0) + 1
        self._failures[channel.name] = missed
        if missed == FAILURES_BEFORE_COMPLAINT:
            log.error(
                "%s has failed %d deliveries in a row. Alerts are not reaching "
                "you through it. Check the configuration.",
                channel.name,
                missed,
            )
        return False
