"""What the traveller gets told, and how it is worded.

An Alert knows its own headline, body and urgency. Delivery is somebody else's
job: Discord takes an Alert and sends it, and knows nothing about routes.
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
        fields = {"Was": event.previous.value}
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
