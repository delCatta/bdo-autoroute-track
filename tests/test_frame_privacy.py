"""Two findings from the security review that needed a decision, not a patch.

**Samples ignored the screenshot policy.** `no_marker` is a whole frame by
nature, because a missing marker only means anything in context. So somebody who
set `notify.screenshot = "marker"` for privacy still accumulated whole window
frames on disk, with chat and a character name in them. They are shrunk now, far
enough that the text is unreadable but still useful as negative examples.

**Screen capture photographs whatever is on top.** It grabs the desktop
rectangle rather than the window, so a browser parked over the game ends up in
the frame and then in a Discord alert. Window capture reads the game's own
buffer and never had this problem.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from bdo_autoroute.archive import Archive
from bdo_autoroute.marker import Box, Sighting
from bdo_autoroute.observation import Observation
from bdo_autoroute.settings import PRIVATE_SAMPLE_WIDTH, Settings
from bdo_autoroute.window import Capture, PreferredCapture, ScreenCapture, Window


def frame() -> Image.Image:
    return Image.new("RGB", (3440, 1440), (20, 20, 30))


def unseen() -> Observation:
    """No sighting, so the sample is the whole frame."""
    return Observation(frame=frame())


def seen() -> Observation:
    """A readable marker, so the sample is an 83x14 digit crop."""
    return Observation(
        frame=frame(),
        sighting=Sighting(0.97, Box(1700, 1080, 17, 16), Box(1614, 1080, 83, 14)),
    )


def archive(settings: Settings) -> Archive:
    return Archive(
        root=Path(tempfile.mkdtemp()),
        keeps_full_frames=settings.keeps_full_frame_samples,
        full_frame_width=settings.sample_frame_width,
    )


class TestSampleWidth:
    def kept(self, mode: str, observation: Observation) -> Image.Image | None:
        path = archive(Settings(screenshot=mode)).keep(observation, match_threshold=0.85)
        return Image.open(path) if path else None

    def test_full_keeps_a_whole_frame_as_it_was(self):
        assert self.kept("full", unseen()).width > PRIVATE_SAMPLE_WIDTH

    def test_marker_shrinks_a_whole_frame(self):
        assert self.kept("marker", unseen()).width == PRIVATE_SAMPLE_WIDTH

    def test_marker_keeps_the_aspect_ratio(self):
        kept = self.kept("marker", unseen())
        assert abs(kept.width / kept.height - 3440 / 1440) < 0.01

    def test_none_writes_no_whole_frame_at_all(self):
        assert self.kept("none", unseen()) is None

    def test_none_still_keeps_the_digit_crop(self):
        """A crop of a number carries nothing private and fixes the OCR bug.

        Dropping it along with the whole frames would remove the evidence for
        the dropped-leading-digit misread and protect nobody.
        """
        assert self.kept("none", seen()) is not None

    def test_a_digit_crop_is_never_shrunk(self):
        assert self.kept("marker", seen()).size == (83, 14)


class TestSettingsPolicy:
    def test_full_frames_are_allowed_unless_screenshots_are_off(self):
        assert Settings(screenshot="full").keeps_full_frame_samples
        assert Settings(screenshot="marker").keeps_full_frame_samples
        assert not Settings(screenshot="none").keeps_full_frame_samples

    def test_only_full_keeps_the_captured_width(self):
        assert Settings(screenshot="full").sample_frame_width is None
        assert Settings(screenshot="marker").sample_frame_width == PRIVATE_SAMPLE_WIDTH


class Fake(Capture):
    def __init__(self, borrows: bool) -> None:
        self._borrows = borrows

    @property
    def borrows_the_desktop(self) -> bool:
        return self._borrows

    def frame(self, window: Window) -> Image.Image:
        return frame()


class TestBorrowsTheDesktop:
    def test_window_capture_does_not_borrow_the_desktop(self):
        assert not Fake(borrows=False).borrows_the_desktop

    def test_screen_capture_borrows_the_desktop(self):
        assert ScreenCapture.borrows_the_desktop.fget(object.__new__(ScreenCapture))

    def test_preferred_follows_whichever_is_in_use(self):
        capture = PreferredCapture(Fake(borrows=False), Fake(borrows=True))
        assert not capture.borrows_the_desktop

    def test_preferred_borrows_once_it_has_fallen_back(self):
        capture = PreferredCapture(Fake(borrows=False), Fake(borrows=True))
        capture._preferred = None
        assert capture.borrows_the_desktop


class TestBorrowedObservation:
    def test_an_observation_is_not_borrowed_by_default(self):
        assert not unseen().borrowed

    def test_a_borrowed_frame_is_still_read(self):
        """The reading still happens. Only the sharing stops.

        A covered window produces no marker, and that is worth reporting as a
        lost route rather than swallowing.
        """
        observation = Observation(frame=frame(), borrowed=True)
        assert observation.frame is not None
        assert not observation.seen


class TestObscured:
    """`obscured` asks Windows what is on top, so it is probed by hand here."""

    def window(self) -> Window:
        return Window(
            hwnd=1,
            title="BLACK DESERT",
            left=0,
            top=0,
            width=3440,
            height=1440,
            frame_left=0,
            frame_top=0,
        )

    def test_it_probes_the_middle_and_four_corners(self):
        assert len(self.window()._probes()) == 5

    def test_every_probe_lands_inside_the_window(self):
        window = self.window()
        for x, y in window._probes():
            assert window.left <= x <= window.left + window.width
            assert window.top <= y <= window.top + window.height

    def test_a_window_owns_its_own_handle(self):
        assert self.window()._owns(1)
