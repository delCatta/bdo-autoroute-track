"""What the traveller gets told, and how it is worded.

An Alert knows its own headline, body and urgency. Delivery is somebody else's
job, so Discord takes an Alert and sends it and knows nothing about routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image

from .voyage import Event, State, Status, duration

COLOURS = {
    State.ARRIVED: 0x2ECC71,
    State.STUCK: 0xE67E22,
    State.SIGNAL_LOST: 0xE74C3C,
    State.TRAVELLING: 0x3498DB,
    State.STARTING: 0x95A5A6,
}


@dataclass(frozen=True)
class Alert:
    """One thing worth interrupting somebody for."""

    headline: str
    body: str
    state: State
    urgent: bool
    screenshot: Image.Image | None = None
    details: dict[str, str] = field(default_factory=dict)

    @property
    def colour(self) -> int:
        return COLOURS.get(self.state, COLOURS[State.TRAVELLING])

    @property
    def stamped_details(self) -> dict[str, str]:
        return {**self.details, "Time": datetime.now().strftime("%H:%M:%S")}

    def thumbnail(self, max_width: int) -> Image.Image | None:
        """The screenshot, shrunk to fit. Every channel wants it smaller."""
        if self.screenshot is None:
            return None
        if self.screenshot.width <= max_width:
            return self.screenshot
        ratio = max_width / self.screenshot.width
        height = max(1, round(self.screenshot.height * ratio))
        return self.screenshot.resize((max_width, height), Image.LANCZOS)

    def showing(self, screenshot: Image.Image | None) -> "Alert":
        if screenshot is None:
            return self
        return Alert(
            self.headline, self.body, self.state, self.urgent, screenshot, self.details
        )

    @classmethod
    def for_event(
        cls, event: Event, *, urgent_states: list[str], details: dict[str, str] | None = None
    ) -> "Alert":
        fields: dict[str, str] = {}
        if event.eta_seconds:
            fields["ETA"] = duration(event.eta_seconds)
        fields.update(details or {})
        return cls(
            headline="Possibly arrived" if event.pending_arrival else event.state.headline,
            body=event.message,
            state=event.state,
            urgent=event.state.value in urgent_states,
            details=fields,
        )

    @classmethod
    def approaching(cls, status: Status) -> "Alert":
        """Close to the destination, in time to do something about it."""
        return cls(
            headline="Approaching destination",
            body=f"{status.distance_m:.0f}m to go.",
            state=status.state,
            urgent=True,
            details={"ETA": duration(status.eta_seconds)},
        )

    @classmethod
    def stalling(cls, status: Status) -> "Alert":
        """Progress has faltered, well before it counts as properly stuck."""
        return cls(
            headline="Progress has stalled",
            body=(
                f"No progress for {duration(status.stalled_seconds)}, "
                f"{status.distance_m:.0f}m remaining. Not yet counted as stuck."
            ),
            state=status.state,
            urgent=True,
        )

    @classmethod
    def still_stuck(cls, status: Status) -> "Alert":
        remaining = (
            f"{status.distance_m:.0f}m still to go."
            if status.distance_m is not None
            else "Distance unknown."
        )
        return cls(
            headline="Still stuck",
            body=f"No progress for {duration(status.stalled_seconds)}. {remaining}",
            state=status.state,
            urgent=True,
        )

    @classmethod
    def watching(cls, status: Status) -> "Alert":
        """The first word after starting up. Watching, and the webhook works.

        Deliberately not "still under way". This fires before any progress has
        been observed, and once claimed motion on a route that had not moved.
        """
        return cls(
            headline="Now watching",
            body=f"{status.distance_m:.0f}m remaining.",
            state=status.state,
            urgent=False,
            details={"ETA": duration(status.eta_seconds)},
        )

    @classmethod
    def heartbeat(cls, status: Status) -> "Alert":
        return cls(
            headline="Still under way",
            body=f"{status.distance_m:.0f}m remaining.",
            state=status.state,
            urgent=False,
            details={"ETA": duration(status.eta_seconds)},
        )

    @classmethod
    def test_message(cls) -> "Alert":
        return cls(
            headline="Test alert",
            body="If you can read this, the webhook is wired up correctly.",
            state=State.TRAVELLING,
            urgent=True,
            details={"Source": "bdo-autoroute-track", "Kind": "manual test"},
        )
