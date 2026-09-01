"""A journey along an auto-route, and what it makes of each distance reading."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

NEW_ROUTE_JUMP_M = 500.0
MAX_CLOSING_SPEED_MPS = 40.0
RATE_WINDOW_SECONDS = 600


class State(str, Enum):
    STARTING = "STARTING"
    TRAVELLING = "TRAVELLING"
    STUCK = "STUCK"
    ARRIVED = "ARRIVED"
    SIGNAL_LOST = "SIGNAL_LOST"

    @property
    def headline(self) -> str:
        return _HEADLINES[self]

    @property
    def trouble(self) -> bool:
        return self in (State.STUCK, State.SIGNAL_LOST)


_HEADLINES = {
    State.STARTING: "Starting up",
    State.TRAVELLING: "Under way",
    State.STUCK: "Looks stuck",
    State.ARRIVED: "Arrived",
    State.SIGNAL_LOST: "Lost sight of the route",
}


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass(frozen=True)
class Event:
    """A change of state worth announcing."""

    state: State
    previous: State
    message: str
    distance_m: float | None
    eta_seconds: float | None
    pending_arrival: bool = False


@dataclass(frozen=True)
class Status:
    """The voyage as it stands after one reading."""

    state: State
    distance_m: float | None
    eta_seconds: float | None
    stalled_seconds: float
    event: Event | None
    pending_arrival: bool = False

    @property
    def changed(self) -> bool:
        return self.event is not None

    @property
    def stuck(self) -> bool:
        return self.state is State.STUCK

    @property
    def travelling(self) -> bool:
        return self.state is State.TRAVELLING


class Progress:
    """How close the route has ever come, and how long ago.

    Stall is measured against the best distance reached rather than the previous
    reading, so jitter and drift never masquerade as movement.
    """

    def __init__(self, epsilon_m: float) -> None:
        self._epsilon = epsilon_m
        self._best: float | None = None
        self._best_at: float | None = None
        self._history: deque[tuple[float, float]] = deque()

    @property
    def best(self) -> float | None:
        return self._best

    def restart(self) -> None:
        self._best = None
        self._best_at = None
        self._history.clear()

    def abandoned_by(self, distance: float) -> bool:
        return self._best is not None and distance > self._best + NEW_ROUTE_JUMP_M

    def record(self, distance: float, now: float) -> None:
        if self._best is None or distance <= self._best - self._epsilon:
            self._best = distance
            self._best_at = now
        self._remember(distance, now)

    def stalled_for(self, now: float) -> float:
        if self._best_at is None:
            return 0.0
        return max(0.0, now - self._best_at)

    def eta(self, distance: float | None) -> float | None:
        if len(self._history) < 2 or distance is None:
            return None
        (began, from_distance), (ended, to_distance) = self._history[0], self._history[-1]
        elapsed, closed = ended - began, from_distance - to_distance
        if elapsed <= 0 or closed <= 0:
            return None
        rate = closed / elapsed
        return None if rate > MAX_CLOSING_SPEED_MPS else distance / rate

    def _remember(self, distance: float, now: float) -> None:
        if self._history and self._implausible(distance, now):
            self._history.clear()
        self._history.append((now, distance))
        while self._history and now - self._history[0][0] > RATE_WINDOW_SECONDS:
            self._history.popleft()

    def _implausible(self, distance: float, now: float) -> bool:
        last_at, last_distance = self._history[-1]
        budget = max(NEW_ROUTE_JUMP_M, MAX_CLOSING_SPEED_MPS * max(0.0, now - last_at))
        return abs(distance - last_distance) > budget


class Voyage:
    """One trip along an auto-route, told through its remaining distance."""

    def __init__(
        self,
        *,
        arrival_threshold_m: float,
        movement_epsilon_m: float,
        stuck_after_seconds: float,
        missing_confirm_polls: int,
        near_arrival_m: float,
        arrival_confirm_polls: int = 2,
    ) -> None:
        self._arrival_threshold = arrival_threshold_m
        self._stuck_after = stuck_after_seconds
        self._missing_confirm = max(1, missing_confirm_polls)
        self._near_arrival = near_arrival_m
        self._arrival_confirm = max(1, arrival_confirm_polls)

        self._progress = Progress(movement_epsilon_m)
        self._state = State.STARTING
        self._distance: float | None = None
        self._missing = 0
        self._arrivals = 0
        self._pending_arrival = False
        self._went_red = False

    @property
    def state(self) -> State:
        return self._state

    @property
    def distance(self) -> float | None:
        return self._distance

    def update(
        self, distance_m: float | None, now: float, *, near_indicator: bool = False
    ) -> Status:
        """Take one reading. `distance_m` is None when nothing could be read."""
        if near_indicator:
            self._went_red = True
        if distance_m is None:
            return self._nothing_seen(now)
        return self._seen(distance_m, now)

    def _seen(self, distance: float, now: float) -> Status:
        previous, self._missing = self._state, 0

        if self._progress.abandoned_by(distance):
            self._start_fresh()
        self._progress.record(distance, now)
        self._distance = distance

        if distance <= self._arrival_threshold:
            return self._arriving(distance, previous, now)

        self._arrivals, self._pending_arrival = 0, False
        stalled = self._progress.stalled_for(now)
        if stalled >= self._stuck_after:
            self._state = State.STUCK
            return self._status(
                previous,
                f"No progress for {duration(stalled)}, {distance:.0f}m remaining.",
                now,
            )

        self._state = State.TRAVELLING
        return self._status(previous, f"Under way, {distance:.0f}m remaining.", now)

    def _arriving(self, distance: float, previous: State, now: float) -> Status:
        self._arrivals += 1
        if self._arrivals >= self._arrival_confirm or self._went_red:
            self._pending_arrival = False
            self._state = State.ARRIVED
            return self._status(previous, f"Arrived, {distance:.0f}m remaining.", now)

        self._pending_arrival = True
        self._state = State.TRAVELLING
        return self._status(
            previous, f"Possibly arrived at {distance:.0f}m, confirming next poll.", now
        )

    def _nothing_seen(self, now: float) -> Status:
        previous = self._state
        self._missing += 1
        if self._missing < self._missing_confirm:
            return self._status(previous, "Nothing readable, waiting.", now)

        if self._close_enough_to_have_arrived:
            self._state = State.ARRIVED
            return self._status(previous, self._arrival_explanation, now)

        self._state = State.SIGNAL_LOST
        return self._status(previous, self._loss_explanation, now)

    @property
    def _close_enough_to_have_arrived(self) -> bool:
        return self._went_red or (
            self._distance is not None and self._distance <= self._near_arrival
        )

    @property
    def _arrival_explanation(self) -> str:
        if self._distance is not None and self._distance <= self._near_arrival:
            return f"Route marker cleared after closing to {self._distance:.0f}m. Arrived."
        return "Route marker cleared right after turning red. Arrived."

    @property
    def _loss_explanation(self) -> str:
        seen = (
            f"last seen at {self._distance:.0f}m"
            if self._distance is not None
            else "no distance was ever read"
        )
        return (
            f"Lost the route marker ({seen}). The client may have crashed, "
            "disconnected, or the marker may be off screen."
        )

    def _start_fresh(self) -> None:
        self._progress.restart()
        self._went_red = False
        self._arrivals = 0
        self._pending_arrival = False

    def _status(self, previous: State, message: str, now: float) -> Status:
        eta = self._progress.eta(self._distance) if self._state is State.TRAVELLING else None
        changed = self._state is not previous
        return Status(
            state=self._state,
            distance_m=self._distance,
            eta_seconds=eta,
            stalled_seconds=self._progress.stalled_for(now),
            pending_arrival=self._pending_arrival,
            event=Event(
                state=self._state,
                previous=previous,
                message=message,
                distance_m=self._distance,
                eta_seconds=eta,
                pending_arrival=self._pending_arrival,
            )
            if changed
            else None,
        )
