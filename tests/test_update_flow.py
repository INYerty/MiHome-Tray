# SPDX-License-Identifier: GPL-3.0-or-later
"""Updater UI and install command tests never execute an installer or close the app."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from app.core import _json_store
from app.core.update_checker import ReleaseInfo
from app.core.update_download import UpdateCancelled
from app.core.update_install import installer_command, start_installer
from app.ui.update_flow import UpdateDialog


@pytest.fixture
def setup_target(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr("app.is_packaged", lambda: True)
    monkeypatch.setattr(_json_store, "data_dir", lambda: tmp_path / "Data")
    folder = tmp_path / "App With Spaces"
    folder.mkdir()
    executable = folder / "MiHome-Tray.exe"
    executable.touch()
    (folder / "_internal").mkdir()
    setup = tmp_path / "Data/updates/9.9.9/MiHome-Tray-Setup-9.9.9-x64.exe"
    setup.parent.mkdir(parents=True)
    setup.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    return setup, folder


def test_install_targets_running_program_without_shell_quoting(setup_target):
    setup, folder = setup_target
    executable, args = installer_command(str(setup))
    assert executable == str(setup)
    assert f"/DIR={folder}" in args and "/APPUPDATE=1" in args
    assert "/SILENT" in args and "/NORESTART" in args


def test_install_rejects_source_mode_and_wrong_download_location(setup_target, monkeypatch, tmp_path):
    setup, folder = setup_target
    foreign = tmp_path / setup.name
    foreign.touch()
    with pytest.raises(RuntimeError, match="路径"):
        installer_command(str(foreign))
    monkeypatch.setattr("app.is_packaged", lambda: False)
    with pytest.raises(RuntimeError, match="源码"):
        installer_command(str(setup))


def test_failed_process_start_raises_without_app_exit(setup_target, monkeypatch):
    monkeypatch.setattr("app.core.update_install.QProcess.startDetached", lambda *args: (False, 0))
    with pytest.raises(RuntimeError, match="启动"):
        start_installer(str(setup_target[0]))


class FakeDownloader(QObject):
    progress = Signal(int, int)
    finished = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.cancelled = False

    def start(self, info):
        self.running = True

    def cancel(self):
        self.cancelled = True

    def complete(self, path="", error=None):
        self.running = False
        self.finished.emit(path, error)


@pytest.fixture
def dialog(qapp, monkeypatch):
    monkeypatch.setattr("app.is_packaged", lambda: True)
    monkeypatch.setattr("app.core.update_download.UpdateDownloader", FakeDownloader)
    info = ReleaseInfo("v9.9.9", "", "演示更新", "https://example.test/setup", "setup.exe", "https://example.test/sums", 100)
    widget = UpdateDialog(info)
    widget.show()
    yield widget
    widget._downloader.running = False
    widget.hide()
    widget.deleteLater()


def test_download_cancel_waits_for_worker_completion(dialog):
    dialog._start()
    dialog._downloader.progress.emit(50, 100)
    assert dialog._bar.value() == 50
    dialog.reject()
    assert dialog._downloader.cancelled and dialog.isVisible()
    dialog._downloader.complete(error=UpdateCancelled("cancel"))
    assert not dialog.isVisible()


def test_hash_or_network_failure_never_installs(dialog, monkeypatch):
    launched = []
    monkeypatch.setattr("app.core.update_install.start_installer", launched.append)
    dialog._start()
    dialog._downloader.complete(error=RuntimeError("SHA256 校验失败"))
    assert not launched and dialog.isVisible()
    assert dialog._install.isEnabled() and "SHA256" in dialog._status.text()


def test_installer_failure_keeps_ui_and_allows_retry(dialog, monkeypatch):
    def fail(path):
        raise RuntimeError("不能启动安装")
    monkeypatch.setattr("app.core.update_install.start_installer", fail)
    dialog._start()
    dialog._downloader.complete("verified.exe")
    assert dialog.isVisible() and dialog._install.isEnabled()
    assert dialog._install.text() == "重试安装"


def test_only_successful_installer_launch_requests_shutdown(dialog, qapp, monkeypatch):
    actions = []
    monkeypatch.setattr("app.core.update_install.start_installer", lambda path: actions.append("launch"))
    monkeypatch.setattr(qapp, "topLevelWidgets", lambda: [SimpleNamespace(request_force_quit=lambda: actions.append("force"))])
    monkeypatch.setattr(qapp, "closeAllWindows", lambda: actions.append("close"))
    monkeypatch.setattr(qapp, "quit", lambda: actions.append("quit"))
    dialog._start()
    dialog._downloader.complete("verified.exe")
    assert actions == ["launch", "force", "close", "quit"]
