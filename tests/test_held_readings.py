"""A refused reading must be visible, not silently swallowed.

A held poll reports the last accepted distance, so in the log it looked exactly
like an ordinary one. Reconstructing a live run from those lines produced a
confident but wrong conclusion about the code. Status now carries what was
refused so the log can say so.
"""

from __future__ import annotations

from bdo_autoroute.voyage import State, Voyage


def voyage(**overrides) -> Voyage:
    settings = {
        "arrival_threshold_m": 70.0,
        "movement_epsilon_m": 15.0,
        "stuck_after_seconds": 180,
        "missing_confirm_polls": 4,
        "near_arrival_m": 400.0,
        "arrival_confirm_polls": 2,
    }
    settings.update(overrides)
    return Voyage(**settings)


class TestHeld:
    def test_held_names_the_refused_reading(self):
        trip = voyage()
        trip.update(858, now=0)
        assert trip.update(3580, now=31).held == 3580

    def test_held_is_none_on_an_ordinary_reading(self):
        trip = voyage()
        trip.update(858, now=0)
        assert trip.update(840, now=31).held is None

    def test_held_clears_once_the_jump_is_confirmed(self):
        trip = voyage()
        trip.update(858, now=0)
        assert trip.update(3580, now=31).held == 3580

        confirmed = trip.update(3580, now=62)
        assert confirmed.held is None
        assert confirmed.distance_m == 3580

    def test_held_is_none_when_nothing_was_read(self):
        trip = voyage()
        trip.update(858, now=0)
        assert trip.update(None, now=31).held is None

    def test_the_reported_distance_still_holds_at_the_old_value(self):
        """The reason this was invisible: the log line looks unchanged."""
        trip = voyage()
        trip.update(858, now=0)
        status = trip.update(3580, now=31)
        assert status.distance_m == 858
        assert status.held == 3580

    def test_a_flicker_keeps_reporting_what_it_refused(self):
        trip = voyage()
        trip.update(1480, now=0)
        for moment, reading in ((31, 480), (62, 1480), (93, 480)):
            status = trip.update(reading, now=moment)
            if reading == 480:
                assert status.held == 480
                assert status.distance_m == 1480


class TestFresh:
    """A poll that read nothing still reports the last known distance.

    Seen live: three consecutive log lines said `TRAVELLING distance=560m
    eta=1m 15s` while the samples archive recorded `no_marker` for every one of
    them. The repeated identical ETA was the only clue, and it reads as "not
    moving" rather than "not seen".
    """

    def test_fresh_is_true_for_a_real_reading(self):
        trip = voyage()
        assert trip.update(858, now=0).fresh

    def test_fresh_is_false_when_nothing_was_read(self):
        trip = voyage()
        trip.update(858, now=0)
        assert not trip.update(None, now=30).fresh

    def test_fresh_is_false_for_a_held_reading(self):
        trip = voyage()
        trip.update(858, now=0)
        assert not trip.update(3580, now=31).fresh

    def test_a_stale_status_still_carries_the_last_distance(self):
        trip = voyage()
        trip.update(560, now=0)
        status = trip.update(None, now=30)
        assert status.distance_m == 560
        assert not status.fresh

    def test_fresh_returns_once_a_reading_comes_back(self):
        trip = voyage()
        trip.update(560, now=0)
        trip.update(None, now=30)
        assert trip.update(540, now=60).fresh


class TestStaleWording:
    def report(self, capsys, updates):
        import logging

        from PIL import Image

        from bdo_autoroute.marker import Offset
        from bdo_autoroute.monitor import Monitor
        from bdo_autoroute.observation import Observation
        from bdo_autoroute.settings import Calibration, Settings

        logging.basicConfig(level=logging.INFO, force=True)
        watcher = Monitor(
            Settings(samples_enabled=False),
            Calibration(Offset(-86, 0, 83, 14), 3440, 1440, "icon_template.png"),
            readout=None,
            outbox=None,
            voyage=None,
        )
        trip = voyage()
        lines = []
        for distance, moment in updates:
            status = trip.update(distance, now=moment)
            captured = []
            watcher._report(status, Observation(Image.new("RGB", (4, 4))))
            lines.append(status)
        return lines

    def test_a_distance_that_never_existed_is_not_called_last_known(self):
        trip = voyage()
        status = trip.update(None, now=0)
        assert status.distance_m is None
        assert not status.fresh

    def test_a_carried_over_distance_is_marked(self):
        trip = voyage()
        trip.update(560, now=0)
        status = trip.update(None, now=30)
        assert status.distance_m == 560
        assert not status.fresh
