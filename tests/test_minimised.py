"""What "minimised" actually means, measured on this machine.

Two DIFFERENT real behaviours, and the difference matters:

    Ordinary window (Tk)   IsIconic=True   client 0x0   rect (-32000,-32000)
                           Graphics Capture delivers NO frame. Truly unreadable.

    Black Desert           IsIconic=FALSE  client 3440x1440 at (0,0)
                           but the window DROPS OUT of the visible enumeration.

So the obvious checks - IsIconic, or a 0x0 client area - never fire for Black
Desert. Before this was measured, minimising the game produced "No visible
window matching ['Black Desert']. Is the game running?", sending the user off to
debug their config when the window was merely minimised.

Because the game keeps a valid rect, capture is ATTEMPTED rather than refused on
principle; only a missing frame proves it cannot be read. Screen-capture
fallback is refused while hidden, since the desktop there shows other apps and
would produce confidently wrong readings rather than an honest failure.
"""

from __future__ import annotations

import pytest

from bdo_tracker.capture import CaptureError, ClientArea, WindowMinimisedError
from bdo_tracker.detector import State, VoyageDetector


def make_area(**overrides) -> ClientArea:
    kwargs = dict(
        left=0, top=0, width=3440, height=1440,
        title="BLACK DESERT - 528853", hwnd=1234,
        window_left=0, window_top=0, window_width=3440, window_height=1440,
    )
    kwargs.update(overrides)
    return ClientArea(**kwargs)


def test_minimised_error_is_a_capture_error() -> None:
    """The monitor loop catches CaptureError; this must not slip past it."""
    assert issubclass(WindowMinimisedError, CaptureError)


def test_client_area_defaults_to_visible() -> None:
    assert make_area().visible is True


def test_hidden_area_is_flagged() -> None:
    """Black Desert keeps a full-size rect while hidden, so size proves nothing."""
    area = make_area(visible=False)
    assert area.visible is False
    assert (area.width, area.height) == (3440, 1440)  # still full size


def test_client_offset_is_unaffected_by_visibility() -> None:
    area = make_area(visible=False, left=8, top=31, window_left=0, window_top=0)
    assert area.client_offset == (8, 31)


# -- how it reaches the user --------------------------------------------


def test_repeated_capture_failures_escalate_to_signal_lost() -> None:
    """A minimised game reaches the user as an alert, not as silence.

    Alerting is right even when they minimised deliberately: staying quiet would
    let them walk away believing the boat was still being watched.
    """
    det = VoyageDetector(
        arrival_threshold_m=70.0,
        movement_epsilon_m=15.0,
        stuck_after_seconds=180,
        missing_confirm_polls=4,
        near_arrival_m=400.0,
    )
    det.update(5000, now=0)
    for t in (30, 60, 90):
        assert det.update(None, now=t).state is State.SAILING   # unconfirmed
    status = det.update(None, now=120)
    assert status.state is State.SIGNAL_LOST
    assert status.event is not None


def test_a_brief_unavailability_is_tolerated() -> None:
    """Restoring the window within the confirmation window changes nothing."""
    det = VoyageDetector(
        arrival_threshold_m=70.0,
        movement_epsilon_m=15.0,
        stuck_after_seconds=180,
        missing_confirm_polls=4,
        near_arrival_m=400.0,
    )
    det.update(5000, now=0)
    det.update(None, now=30)
    det.update(None, now=60)
    status = det.update(4900, now=90)      # restored in time
    assert status.state is State.SAILING
    assert status.event is None


@pytest.mark.parametrize(
    ("iconic", "client", "unreadable"),
    [
        (True, (0, 0), True),        # ordinary minimised window
        (False, (0, 0), True),       # zero-sized: unreadable whatever IsIconic says
        (False, (3440, 1440), False),  # Black Desert hidden: rect intact, so try
    ],
)
def test_which_states_are_refused_outright(
    iconic: bool, client: tuple[int, int], unreadable: bool
) -> None:
    """Mirrors the guard in find_client_area, without needing a real window."""
    cw, ch = client
    refused = iconic or cw <= 0 or ch <= 0
    assert refused is unreadable
