# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct per-device controls and persisted visibility with isolated preferences."""
from dataclasses import replace
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest

from app.core import _json_store, settings_store
from app.core.models import DeviceDetail, PropInfo
from app.core.quick_controls import QuickControlSession
from app.ui.tray.device_controls import QuickDeviceCard
from tests.test_quick_controls import FAN, LAMP, FakeService, ImmediateJobs, FAN_PROPS


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    monkeypatch.setattr(_json_store, "data_file", lambda name: tmp_path / name)


@pytest.fixture
def lamp(qapp):
    state = QuickControlSession(LAMP, FakeService(), ImmediateJobs())
    state.refresh()
    card = QuickDeviceCard(state)
    card.resize(400, 260)
    card.show()
    qapp.processEvents()
    yield card, state
    card.hide()
    state._send_timer.stop()
    state._confirm_timer.stop()
    card.deleteLater()
    state.deleteLater()


def test_power_and_color_temperature_visible_inside_same_device_frame(lamp):
    card, state = lamp
    assert card._power.isVisible()
    assert card._power.parentWidget() is card
    assert card._lines["brightness"].isVisible()
    assert card._lines["color-temperature"].isVisible()
    assert all(line.parentWidget() is card for line in card._lines.values())
    assert not hasattr(card, "_extra")
    card._power.click()
    state._send_timer.stop()
    state._send_write()
    assert state.service.writes == [(LAMP.did, "on", False)]


def test_visibility_menu_changes_only_own_device_and_survives_recreation(lamp, qapp):
    card, state = lamp
    card._populate_visibility_menu()
    action = next(action for action in card._control_menu.actions() if "色温" in action.text())
    action.setChecked(False)
    assert card._lines["color-temperature"].isHidden()
    assert card._lines["brightness"].isVisible()
    assert settings_store.get_tray_hidden_controls(LAMP.did) == {"color-temperature"}
    assert not settings_store.get_tray_hidden_controls(FAN.did)
    other = QuickDeviceCard(state)
    other.show()
    qapp.processEvents()
    assert other._lines["color-temperature"].isHidden()
    other.set_control_visible("on", False)
    assert other._power.isHidden()
    other._show_all()
    assert other._power.isVisible() and other._lines["color-temperature"].isVisible()
    other.hide()
    other.deleteLater()


def test_color_temperature_operates_without_expanding_or_opening_details(lamp):
    card, state = lamp
    slider = card._controls["color-temperature"][1]
    opened = QSignalSpy(card.open_details)
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(60, 20))
    assert not state.service.writes
    QTest.mouseMove(slider, QPoint(220, 20))
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(220, 20))
    state._send_timer.stop()
    state._send_write()
    assert len(state.service.writes) == 1
    did, name, value = state.service.writes[0]
    assert did == LAMP.did and name == "color-temperature" and (value - 2700) % 100 == 0
    assert opened.count() == 0


def test_sparse_fan_segments_submit_only_original_metadata_values(qapp):
    service = FakeService()
    props = [replace(prop, range=None, value_list=[
        {"value": 2, "description": "一档"}, {"value": 8, "description": "二档"},
        {"value": 31, "description": "三档"}]) if prop.name == "fan-level" else prop for prop in FAN_PROPS]
    service.device_detail = lambda did: DeviceDetail(did, FAN.name, FAN.model, props, [])
    service.by_device[FAN.did]["fan-level"] = 8
    state = QuickControlSession(FAN, service, ImmediateJobs())
    state.refresh()
    card = QuickDeviceCard(state)
    card.resize(400, 300)
    card.show()
    qapp.processEvents()
    slider = card._controls["fan-level"][1]
    assert slider.segments == ("一档", "二档", "三档")
    assert slider.value() == 1 and card._lines["fan-level"].isVisible()
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(slider.width() - 10, 20))
    assert not service.writes
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(slider.width() - 10, 20))
    state._send_timer.stop()
    state._send_write()
    assert service.writes == [(FAN.did, "fan-level", 31)]
    state._confirm_timer.stop()
    state._read()
    service.by_device[FAN.did]["fan-level"] = 999
    state.refresh()
    assert not slider.isEnabled() and slider.isUnknown()
    assert "未知" in card._summary.text()
    card.hide()
    state._send_timer.stop()
    state._confirm_timer.stop()
    card.deleteLater()
    state.deleteLater()


def test_hiding_an_active_control_cancels_local_drag_without_a_write(lamp):
    card, state = lamp
    slider = card._controls["brightness"][1]
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(100, 20))
    assert state.editing
    card.set_control_visible("brightness", False)
    assert not state.editing and not slider.isSliderDown()
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(200, 20))
    assert not state.service.writes and state.requested is None
