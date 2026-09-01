"""The heartbeat went silent for a whole voyage. Found live, 2026-09-01.

`Now watching` fired near the end of a route, at roughly 420m, which set the
progress baseline to 420. A new route then began at 9200m, and the gate asks
whether `baseline - distance` clears 150m. That is `420 - 9200`, so it went
quiet and stayed quiet: the only way back was for the new route to become
shorter than the old one had been.

Twelve minutes and 7000m of real travel produced no alert at all, on a config
asking for one every minute. It presented as "Discord stopped working", and the
logs showed polling working perfectly with nothing being sent, because nothing
was being generated.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from bdo_autoroute.marker import Offset
from bdo_autoroute.monitor import Monitor
from bdo_autoroute.outbox import Outbox
from bdo_autoroute.settings import Calibration, Settings
from bdo_autoroute.voyage import State, Status, Voyage


def monitor(**overrides) -> Monitor:
    settings = Settings(heartbeat_minutes=1, heartbeat_min_progress_m=150.0, **overrides)
    return Monitor(
        settings,
        Calibration(Offset(-86, 0, 83, 14), 3440, 1440, "icon_template.png"),
        readout=None,
        outbox=Outbox([]),
        voyage=Voyage(
            arrival_threshold_m=70.0,
            movement_epsilon_m=15.0,
            stuck_after_seconds=180,
            missing_confirm_polls=4,
            near_arrival_m=400.0,
        ),
        samples_dir=Path(tempfile.mkdtemp()),
    )


def travelling(distance: float) -> Status:
    return Status(State.TRAVELLING, distance, None, 0.0, None)


class TestWorthAHeartbeat:
    def test_the_first_one_always_counts(self):
        watcher = monitor()
        assert watcher._worth_a_heartbeat(travelling(3970), now=100.0)

    def test_it_waits_for_real_ground_to_be_covered(self):
        watcher = monitor()
        watcher._worth_a_heartbeat(travelling(3970), now=100.0)
        assert not watcher._worth_a_heartbeat(travelling(3900), now=200.0)

    def test_it_speaks_once_the_ground_is_covered(self):
        watcher = monitor()
        watcher._worth_a_heartbeat(travelling(3970), now=100.0)
        assert watcher._worth_a_heartbeat(travelling(3800), now=200.0)

    def test_a_longer_new_route_does_not_silence_it_forever(self):
        """The bug. A baseline from the end of one route killed the next."""
        watcher = monitor()
        watcher._worth_a_heartbeat(travelling(420), now=100.0)

        assert not watcher._worth_a_heartbeat(travelling(9200), now=200.0)
        assert watcher._last_heartbeat_distance == 9200

        assert watcher._worth_a_heartbeat(travelling(9000), now=300.0)

    def test_it_keeps_speaking_across_the_whole_new_route(self):
        """The live case, 9200m down to 2030m, which produced nothing at all."""
        watcher = monitor()
        watcher._worth_a_heartbeat(travelling(420), now=100.0)
        watcher._worth_a_heartbeat(travelling(9200), now=200.0)

        spoke = 0
        for i, distance in enumerate(range(9000, 2000, -200), start=3):
            if watcher._worth_a_heartbeat(travelling(float(distance)), now=i * 100.0):
                spoke += 1
        assert spoke >= 20

    def test_the_clock_still_gates_it(self):
        watcher = monitor()
        watcher._worth_a_heartbeat(travelling(9200), now=100.0)
        assert not watcher._worth_a_heartbeat(travelling(8000), now=110.0)

    def test_nothing_read_means_no_heartbeat(self):
        watcher = monitor()
        assert not watcher._worth_a_heartbeat(
            Status(State.TRAVELLING, None, None, 0.0, None), now=100.0
        )

    def test_sitting_still_stays_quiet(self):
        watcher = monitor()
        watcher._worth_a_heartbeat(travelling(3970), now=100.0)
        for i in range(2, 8):
            assert not watcher._worth_a_heartbeat(travelling(3970), now=i * 100.0)
