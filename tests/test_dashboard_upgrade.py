# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-view regressions, with isolated preferences and simulated devices."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from app.core import _json_store, settings_store, tray_store
from app.core.models import ActionInfo, DeviceDetail, DeviceInfo
from app.ui.speaker_commands import SpeakerCommands
from app.ui.tray.quick_window import TrayQuickWindow
from tests.test_quick_controls import FakeService, ImmediateJobs, LAMP, FAN


SPEAKER = DeviceInfo("test-speaker", "客厅小爱", "xiaomi.wifispeaker.test", "家", "客厅", True)
ROUTER = DeviceInfo("test-router", "家庭路由器", "xiaomi.router.test", "家", "书房", True)


class DashboardService(FakeService):
    def __init__(self):
        super().__init__()
        self.actions = []

    def device_detail(self, did):
        if did == SPEAKER.did:
            return DeviceDetail(did, SPEAKER.name, SPEAKER.model, [],
                                [ActionInfo("execute-text-directive", "执行文字指令")])
        if did == ROUTER.did:
            return DeviceDetail(did, ROUTER.name, ROUTER.model, [], [])
        return super().device_detail(did)

    def run_action(self, did, name, params=None):
        self.actions.append((did, name, params))

    def power_states(self, dids):
        return {did: None for did in dids}

    def read_metrics(self, dids):
        return {}

    def read_prop(self, did, name):
        return self.values.get(name)

    def router_snapshot(self, did):
        from app.core.router import RouterSnapshot, discover_router
        from tests.test_router import fixture_spec
        return RouterSnapshot(discover_router(fixture_spec()),
                              {"2.1": 1250000, "2.2": 8300, "2.3": 8}, 100)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(_json_store, "data_file", lambda name: tmp_path / name)


def make_tray():
    devices = [LAMP, FAN, SPEAKER, ROUTER]
    tray_store.save([device.did for device in devices])
    window = TrayQuickWindow(DashboardService(), ImmediateJobs())
    window._install_outside_filter = lambda: None
    window._registry.confirm_presence(devices)
    window.set_devices(devices, {})
    return window


def test_resized_tray_survives_refresh_and_reopen(qapp):
    window = make_tray()
    window.show_near_tray()
    qapp.processEvents()
    window.resize(510, 610)
    qapp.processEvents()
    window._rebuild()
    window._sync_tray_height()
    assert (window.width(), window.height()) == (510, 610)
    window.abort_toggle_animation()
    window.hide()
    assert settings_store.get_tray_size() == (510, 610)
    window.show_near_tray()
    qapp.processEvents()
    assert (window.width(), window.height()) == (510, 610)
    window.abort_toggle_animation()
    window.hide()
    window.deleteLater()


def test_inline_speaker_and_router_never_request_main_details(qapp):
    window = make_tray()
    opened = []
    window.open_device_requested.connect(opened.append)
    window.show_near_tray()
    qapp.processEvents()
    window._open_inline(SPEAKER.did)
    qapp.processEvents()
    assert window._stack.currentWidget() is window._detail_page
    commands = window._detail_scroll.widget().findChild(SpeakerCommands)
    assert commands is not None and commands._action == "execute-text-directive"
    window._back_to_devices()
    window._open_inline(ROUTER.did)
    qapp.processEvents()
    from app.ui.router_panel import RouterPanel
    router = window._detail_scroll.widget().findChild(RouterPanel)
    assert router is not None and router._graphs
    assert window._detail_scroll.widget().width() <= window._detail_scroll.viewport().width()
    assert not opened
    window.abort_toggle_animation()
    window.hide()
    assert not router._timer.isActive()
    window.deleteLater()


def test_saved_commands_are_per_device_and_run_exact_text(qapp):
    service = DashboardService()
    panel = SpeakerCommands(service, ImmediateJobs(), SPEAKER)
    panel.show()
    qapp.processEvents()
    panel._edit_command(None)
    panel._title.setText("晚安")
    panel._text.setText("关闭卧室灯")
    panel._save()
    item = settings_store.get_speaker_commands(SPEAKER.did)[0]
    assert item == {"title": "晚安", "text": "关闭卧室灯"}
    assert not settings_store.get_speaker_commands("other-account-device")
    panel._run(item)
    assert service.actions == [(SPEAKER.did, "execute-text-directive", ["关闭卧室灯"])]
    panel.retheme()
    panel.hide()
    panel.deleteLater()


def test_unsupported_or_offline_speaker_never_sends(qapp):
    service = DashboardService()
    service.device_detail = lambda did: DeviceDetail(did, "test", "test", [], [])
    panel = SpeakerCommands(service, ImmediateJobs(), SPEAKER)
    panel.show()
    qapp.processEvents()
    panel._run({"title": "test", "text": "开灯"})
    assert not service.actions
    panel._action = "execute-text-directive"
    panel.device = replace(SPEAKER, online=False)
    panel._run({"title": "test", "text": "开灯"})
    assert not service.actions
    panel.hide()
    panel.deleteLater()


def test_quick_order_persists_and_resize_reflows(qapp):
    window = make_tray()
    window.show_near_tray()
    qapp.processEvents()
    order = [f"device:{device.did}" for device in (ROUTER, FAN, SPEAKER, LAMP)]
    window._save_quick_order(order)
    qapp.processEvents()
    assert [item["id"] for item in tray_store.load_order()] == [ROUTER.did, FAN.did, SPEAKER.did, LAMP.did]
    window._columns = 2
    window.resize(740, 610)
    qapp.processEvents()
    assert window._layout_columns == 2
    window.resize(400, 610)
    qapp.processEvents()
    assert window._layout_columns == 1
    assert window._grid.count() == 4
    window.abort_toggle_animation()
    window.hide()
    window.deleteLater()


def test_tray_rebuild_does_not_end_a_homepage_slider_gesture(qapp):
    window = make_tray()
    window.show_near_tray()
    qapp.processEvents()
    session = window._registry.sessions[LAMP.did]
    session.editing = True  # A separate view owns the current pointer gesture.
    window._rebuild()
    assert session.editing
    window.abort_toggle_animation()
    window.hide()
    assert session.editing
    session.editing = False
    window.deleteLater()


def test_enter_submits_text_once_without_starting_microphone(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window = make_tray()
    window.show_near_tray()
    qapp.processEvents()
    microphone_starts = []
    window._mic.capture.start = lambda: microphone_starts.append(True)
    window._voice_edit.setFocus()
    window._voice_edit.setText("打开卧室灯")
    QTest.keyClick(window._voice_edit, Qt.Key_Return)
    qapp.processEvents()
    assert not microphone_starts
    assert window._service.actions == [(SPEAKER.did, "execute-text-directive", ["打开卧室灯"])]
    window.abort_toggle_animation()
    window.hide()
    window.deleteLater()


def test_ambient_stops_when_hidden_or_disabled(qapp):
    from app.ui.dashboard_surface import DashboardSurface
    settings_store.set_ambient_enabled(True)
    surface = DashboardSurface()
    surface.resize(500, 400)
    surface.show()
    qapp.processEvents()
    assert surface._timer.isActive()
    assert not surface.grab().isNull()
    settings_store.set_ambient_enabled(False)
    surface.sync_effects()
    assert not surface._timer.isActive()
    surface.hide()
    surface.deleteLater()
