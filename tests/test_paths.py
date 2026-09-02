"""Where the program keeps things depends on how it was started.

From a checkout, everything sits beside the code, which is what a developer
expects. From the installed exe it cannot: the install folder is replaced
wholesale on every update and a calibration must outlive that. So the exe
keeps its own files under %LOCALAPPDATA% and reads shipped ones from the
unpacked bundle.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bdo_autoroute import settings

CHECKOUT = Path(settings.__file__).resolve().parents[2]


def packaged(monkeypatch, tmp_path: Path) -> Path:
    unpacked = tmp_path / "install" / "_internal"
    unpacked.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(unpacked), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return unpacked


class TestHome:
    def test_home_is_the_checkout_when_run_from_source(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert settings.home() == CHECKOUT

    def test_home_moves_under_local_appdata_when_packaged(self, monkeypatch, tmp_path):
        packaged(monkeypatch, tmp_path)
        assert settings.home() == tmp_path / "appdata" / settings.APP_NAME

    def test_home_is_created_so_the_first_save_has_somewhere_to_go(self, monkeypatch, tmp_path):
        packaged(monkeypatch, tmp_path)
        assert settings.home().is_dir()

    def test_home_is_never_inside_the_install(self, monkeypatch, tmp_path):
        unpacked = packaged(monkeypatch, tmp_path)
        assert not settings.home().is_relative_to(unpacked.parent)


class TestBundle:
    def test_bundle_is_the_checkout_when_run_from_source(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert settings.bundle() == CHECKOUT

    def test_bundle_is_the_unpacked_folder_when_packaged(self, monkeypatch, tmp_path):
        unpacked = packaged(monkeypatch, tmp_path)
        assert settings.bundle() == unpacked

    def test_shipped_files_are_read_from_the_bundle(self):
        assert settings.EXAMPLE_CONFIG.parent == settings.BUNDLE
        assert settings.ASSETS.parent == settings.BUNDLE

    def test_written_files_land_in_home(self):
        for path in (settings.CONFIG, settings.CALIBRATION, settings.ICON):
            assert path.parent == settings.ROOT
