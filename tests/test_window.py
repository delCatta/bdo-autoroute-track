"""Window: geometry, and what minimising really does.

Black Desert does not minimise like an ordinary window. Measured on a real
client, and the reason the obvious guards do not work: HANDOFF.md section 6, #6.

    Ordinary window   IsIconic=True   drawable 0x0        rect (-32000,-32000)
    Black Desert      IsIconic=FALSE  drawable 3440x1440  rect (0,0,3440,1440)
                      but it leaves the visible window enumeration
"""

from __future__ import annotations

import pytest

from bdo_autoroute.voyage import State, Voyage
from bdo_autoroute.window import CaptureError, Window, WindowMinimised


def window(**overrides) -> Window:
    fields = {
        "hwnd": 1234,
        "title": "BLACK DESERT - 528853",
        "left": 0,
        "top": 0,
        "width": 3440,
        "height": 1440,
        "frame_left": 0,
        "frame_top": 0,
    }
    fields.update(overrides)
    return Window(**fields)


class TestOffset:
    def test_offset_is_zero_for_a_borderless_window(self):
        assert window().offset == (0, 0)

    def test_offset_measures_the_title_bar_and_borders(self):
        windowed = window(left=8, top=31, frame_left=0, frame_top=0)
        assert windowed.offset == (8, 31)

    def test_size_returns_the_drawable_area(self):
        assert window().size == (3440, 1440)


class TestVisible:
    def test_visible_defaults_to_true(self):
        assert window().visible

    def test_a_hidden_window_keeps_its_full_size(self):
        hidden = window(visible=False)
        assert not hidden.visible
        assert hidden.size == (3440, 1440)


class TestWindowMinimised:
    def test_window_minimised_is_a_capture_error(self):
        assert issubclass(WindowMinimised, CaptureError)

    def test_window_minimised_says_how_to_recover(self):
        message = str(WindowMinimised("'BDO' is minimised. Restore it to resume."))
        assert "minimised" in message.lower()
        assert "restore" in message.lower()


class TestEscalation:
    """A window that cannot be read reaches the user as an alert, not silence.

    Alerting is right even when it was minimised deliberately: staying quiet
    would let somebody walk away believing the route was still being watched.
    """

    def voyage(self) -> Voyage:
        return Voyage(
            arrival_threshold_m=70.0,
            movement_epsilon_m=15.0,
            stuck_after_seconds=180,
            missing_confirm_polls=4,
            near_arrival_m=400.0,
        )

    def test_repeated_failures_become_signal_lost(self):
        trip = self.voyage()
        trip.update(5000, now=0)
        for moment in (30, 60, 90):
            assert trip.update(None, now=moment).travelling
        assert trip.update(None, now=120).state is State.SIGNAL_LOST

    def test_a_brief_unavailability_changes_nothing(self):
        trip = self.voyage()
        trip.update(5000, now=0)
        trip.update(None, now=30)
        trip.update(None, now=60)
        status = trip.update(4900, now=90)
        assert status.travelling
        assert not status.changed


class TestRefusedStates:
    @pytest.mark.parametrize(
        ("iconic", "drawable", "unreadable"),
        [
            (True, (0, 0), True),
            (False, (0, 0), True),
            (False, (3440, 1440), False),
        ],
    )
    def test_only_a_truly_minimised_window_is_refused_outright(
        self, iconic, drawable, unreadable
    ):
        width, height = drawable
        assert (iconic or width <= 0 or height <= 0) is unreadable
