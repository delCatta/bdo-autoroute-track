"""A toast made on one thread and shown from another delivers nothing.

Found on the first run of the installed exe. The window builds the outbox on
Tk's thread and the poll loop delivers from a worker. Windows answered
"The application called an interface that was marshalled for a different
thread", the toast never appeared, and the log recorded a warning nobody was
looking at. The tray-only run never hit it because there the outbox was built
on the thread that used it.

So the toaster is made lazily, on whichever thread delivers.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

from bdo_autoroute.alerts import Alert
from bdo_autoroute.desktop import Desktop


class FakeToaster:
    made_on: list[int] = []

    def __init__(self, app_name: str) -> None:
        FakeToaster.made_on.append(threading.get_ident())

    def show_toast(self, toast) -> None:
        pass


class FakeToast:
    def __init__(self) -> None:
        self.text_fields: list[str] = []


@pytest.fixture
def windows_toasts(monkeypatch):
    module = types.ModuleType("windows_toasts")
    module.WindowsToaster = FakeToaster
    module.Toast = FakeToast
    monkeypatch.setitem(sys.modules, "windows_toasts", module)
    FakeToaster.made_on.clear()
    return module


def delivered_on_a_worker(desktop: Desktop) -> int:
    worker_ident = []

    def deliver() -> None:
        worker_ident.append(threading.get_ident())
        assert desktop.deliver(Alert.test_message())

    worker = threading.Thread(target=deliver)
    worker.start()
    worker.join()
    return worker_ident[0]


class TestToasterThread:
    def test_making_a_desktop_makes_no_toaster(self, windows_toasts):
        Desktop()
        assert FakeToaster.made_on == []

    def test_the_toaster_is_made_on_the_thread_that_delivers(self, windows_toasts):
        desktop = Desktop()
        worker = delivered_on_a_worker(desktop)
        assert FakeToaster.made_on == [worker]
        assert worker != threading.get_ident()

    def test_a_thread_keeps_its_toaster(self, windows_toasts):
        desktop = Desktop()
        desktop.deliver(Alert.test_message())
        desktop.deliver(Alert.test_message())
        assert len(FakeToaster.made_on) == 1
