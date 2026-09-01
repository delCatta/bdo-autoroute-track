"""Turn a stream of distance readings into voyage state and alertable events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

# If the distance jumps up by more than this, the old voyage is over and a new
# auto-route has been set. Anything smaller is OCR jitter or the boat drifting.
NEW_VOYAGE_JUMP_M = 500.0

# How much recent history to keep for the speed/ETA estimate.
_RATE_WINDOW_SECONDS = 600

# Fastest closing speed a ship can plausibly manage. Live readings cruise at
# roughly 20 m/s, so this leaves generous headroom. Used only to recognise that
# a change cannot be sailing - it is a new route or a misread - so the rate
# estimate is not poisoned by it.
MAX_CLOSING_SPEED_MPS = 40.0


class State(str, Enum):
    STARTING = "STARTING"        # no successful reading yet
    SAILING = "SAILING"          # distance is falling
    STUCK = "STUCK"              # distance has not improved for too long
    ARRIVED = "ARRIVED"          # at (or effectively at) the destination
    SIGNAL_LOST = "SIGNAL_LOST"  # readout vanished while still far out


@dataclass(frozen=True)
class Event:
    """A state change worth telling the user about."""

    state: State
    previous: State
    message: str
    distance_m: float | None
    eta_seconds: float | None
    # True for the one poll between a first sub-threshold reading and its
    # confirmation, so the alert does not say "Under way" over an arrival body.
    pending_arrival: bool = False


@dataclass(frozen=True)
class Status:
    """The detector's view of the world after one poll."""

    state: State
    distance_m: float | None
    eta_seconds: float | None
    stalled_seconds: float
    event: Event | None  # non-None only on a transition
    pending_arrival: bool = False


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class VoyageDetector:
    """State machine over distance readings.

    Stuck detection tracks the best (smallest) distance seen and how long ago it
    was seen, rather than diffing consecutive readings. That absorbs OCR jitter
    and brief upward blips without ever missing a genuinely stalled boat.
    """

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
        self._epsilon = movement_epsilon_m
        self._stuck_after = stuck_after_seconds
        self._missing_confirm = max(1, missing_confirm_polls)
        self._near_arrival = near_arrival_m
        self._arrival_confirm = max(1, arrival_confirm_polls)
        self._arrival_streak = 0
        self._pending_arrival = False

        self._state = State.STARTING
        self._best_distance: float | None = None
        self._best_time: float | None = None
        self._last_distance: float | None = None
        self._missing_count = 0
        self._history: deque[tuple[float, float]] = deque()
        # The game turns the readout red when you are close. Remembered so a
        # readout that vanishes right afterwards is read as arrival, not loss.
        self._saw_near_indicator = False

    @property
    def state(self) -> State:
        return self._state

    @property
    def last_distance(self) -> float | None:
        return self._last_distance

    def update(
        self, distance_m: float | None, now: float, *, near_indicator: bool = False
    ) -> Status:
        """Feed one poll in.

        `distance_m` is None when the readout was unreadable. `near_indicator`
        is True when the readout has turned red, which the game does only when
        you are close to the destination.
        """
        if near_indicator:
            self._saw_near_indicator = True
        if distance_m is None:
            return self._on_missing(now)
        return self._on_reading(distance_m, now)

    # -- reading present -------------------------------------------------

    def _on_reading(self, distance: float, now: float) -> Status:
        self._missing_count = 0
        previous = self._state

        # A large jump upward means a fresh auto-route was set.
        if self._best_distance is not None and distance > self._best_distance + NEW_VOYAGE_JUMP_M:
            self._reset_progress()

        if self._best_distance is None or distance <= self._best_distance - self._epsilon:
            self._best_distance = distance
            self._best_time = now
        self._last_distance = distance
        self._record_history(distance, now)

        if distance <= self._arrival_threshold:
            self._arrival_streak += 1
            # A single sub-threshold reading is not enough. A live frame once
            # OCR'd 1169m as "9", which would have declared a false arrival and
            # stopped the user paying attention. Confirmation costs one poll,
            # and the red indicator short-circuits it when the game agrees.
            if self._arrival_streak >= self._arrival_confirm or self._saw_near_indicator:
                self._pending_arrival = False
                self._state = State.ARRIVED
                message = f"Boat has arrived. Remaining distance {distance:.0f}m."
                return self._status(previous, message, now)
            self._pending_arrival = True
            self._state = State.SAILING
            message = f"Possible arrival at {distance:.0f}m; confirming next poll."
            return self._status(previous, message, now)

        self._arrival_streak = 0
        self._pending_arrival = False

        stalled = self._stalled_seconds(now)
        if stalled >= self._stuck_after:
            self._state = State.STUCK
            message = (
                f"Boat appears stuck: {distance:.0f}m remaining and no progress "
                f"for {format_duration(stalled)}."
            )
            return self._status(previous, message, now)

        self._state = State.SAILING
        return self._status(previous, f"Sailing, {distance:.0f}m remaining.", now)

    # -- reading absent --------------------------------------------------

    def _on_missing(self, now: float) -> Status:
        previous = self._state
        self._missing_count += 1

        if self._missing_count < self._missing_confirm:
            # Not enough evidence yet; hold the current state.
            return self._status(previous, "Readout unreadable; waiting for confirmation.", now)

        # The readout is gone. Arrival is the explanation if we were already
        # close by distance, or if the game had turned the text red.
        was_close = self._last_distance is not None and self._last_distance <= self._near_arrival
        if was_close or self._saw_near_indicator:
            self._state = State.ARRIVED
            why = (
                f"after closing to {self._last_distance:.0f}m"
                if was_close
                else "right after the readout turned red"
            )
            message = f"Route indicator cleared {why}. Boat has arrived."
            return self._status(previous, message, now)

        self._state = State.SIGNAL_LOST
        last = (
            f"last seen at {self._last_distance:.0f}m"
            if self._last_distance is not None
            else "no distance was ever read"
        )
        message = (
            f"Lost the route readout ({last}). The client may have crashed, "
            "disconnected, or the UI may be hidden."
        )
        return self._status(previous, message, now)

    # -- helpers ---------------------------------------------------------

    def _reset_progress(self) -> None:
        self._best_distance = None
        self._best_time = None
        self._history.clear()
        self._saw_near_indicator = False
        self._arrival_streak = 0

    def _record_history(self, distance: float, now: float) -> None:
        # A change no ship could have sailed means a new route was set (or a
        # misread happened). Either way the samples either side of it describe
        # different journeys, so averaging across the gap yields a nonsense
        # speed - a live route change once produced "eta=0s". Start over.
        if self._history:
            last_time, last_distance = self._history[-1]
            budget = max(
                NEW_VOYAGE_JUMP_M, MAX_CLOSING_SPEED_MPS * max(0.0, now - last_time)
            )
            if abs(distance - last_distance) > budget:
                self._history.clear()

        self._history.append((now, distance))
        while self._history and now - self._history[0][0] > _RATE_WINDOW_SECONDS:
            self._history.popleft()

    def _stalled_seconds(self, now: float) -> float:
        if self._best_time is None:
            return 0.0
        return max(0.0, now - self._best_time)

    def _eta_seconds(self) -> float | None:
        """Estimate time to arrival from the recent rate of closure."""
        if len(self._history) < 2 or self._last_distance is None:
            return None
        (t0, d0), (t1, d1) = self._history[0], self._history[-1]
        elapsed = t1 - t0
        closed = d0 - d1
        if elapsed <= 0 or closed <= 0:
            return None
        rate = closed / elapsed  # metres per second
        if rate > MAX_CLOSING_SPEED_MPS:
            # No ship closes this fast, so the estimate is built on a jump.
            # Saying nothing beats reporting a confidently wrong ETA.
            return None
        return self._last_distance / rate

    def _status(self, previous: State, message: str, now: float) -> Status:
        # ETA is only meaningful while under way.
        eta = self._eta_seconds() if self._state is State.SAILING else None
        event = (
            Event(
                state=self._state,
                previous=previous,
                message=message,
                distance_m=self._last_distance,
                eta_seconds=eta,
                pending_arrival=self._pending_arrival,
            )
            if self._state is not previous
            else None
        )
        return Status(
            state=self._state,
            distance_m=self._last_distance,
            eta_seconds=eta,
            stalled_seconds=self._stalled_seconds(now),
            event=event,
            pending_arrival=self._pending_arrival,
        )
