# SPDX-License-Identifier: GPL-3.0-or-later
"""Primary tile controls use the shared capability/state owner, never fake values."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest

from app.core.models import DeviceInfo, PropInfo
from app.core.quick_controls import QuickControlSession
from app.ui.device_card import DeviceCard
from tests.test_quick_controls import FAN, LAMP, FakeService, ImmediateJobs


@pytest.fixture
def state(qapp):
    session = QuickControlSession(LAMP, FakeService(), ImmediateJobs())
    yield session
    session._send_timer.stop()
    session._confirm_timer.stop()
    session.deleteLater()


@pytest.fixture
def card(qapp, state):
    widget = DeviceCard(LAMP, session=state)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def test_unknown_tile_has_no_invented_brightness(card, state):
    assert card._sub_label.text() == "读取中…"
    assert not card._slider.isEnabled()
    assert card._power_btn.isHidden()
    state.refresh()
    assert card._sub_label.text() == "50%"
    assert card._slider.isEnabled()
    assert card._slider.value() == 49  # published range is 1..100, index 49 means 50


def test_presence_failure_disables_both_primary_and_power(card, state):
    state.refresh()
    assert card._power_btn.isEnabled()
    state.presence_known = False
    state.changed.emit()
    assert not card._power_btn.isEnabled()
    assert not card._slider.isEnabled()
    assert card._sub_label.text() == "在线状态待确认"


def test_slider_commits_once_on_release_and_does_not_open_details(card, state, qapp):
    state.refresh()
    opened = QSignalSpy(card.open_requested)
    slider = card._slider
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(80, 20))
    assert state.editing
    assert not state.service.writes
    QTest.mouseMove(slider, QPoint(200, 20))
    assert not state.service.writes
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(200, 20))
    assert not state.editing
    assert state.requested[0] == "brightness"
    QTest.qWait(210)
    assert len(state.service.writes) == 1
    assert state.service.writes[0][:2] == (LAMP.did, "brightness")
    assert opened.count() == 0


def test_unsupported_primary_control_compacts_after_metadata(card, state):
    state._loaded = True
    state.props = []
    state.values = {}
    state.changed.emit()
    assert card.height() == 68
    assert card._slider.isHidden()
    assert card._power_btn.isHidden()


def test_fan_uses_published_speed_range(qapp):
    state = QuickControlSession(FAN, FakeService(), ImmediateJobs())
    state.refresh()
    card = DeviceCard(FAN, session=state)
    assert card._primary_prop.name == "fan-level"
    assert card._sub_label.text() == "风速 35"
    assert card._slider.maximum() == 99
    card.deleteLater()
    state.deleteLater()


def test_card_drag_release_does_not_activate_details(qapp):
    device = DeviceInfo("test-sensor", "温湿度计", "miaomiao.sensor_ht.t2", "家", "客厅", True)
    card = DeviceCard(device)
    card.show()
    qapp.processEvents()
    opened = QSignalSpy(card.open_requested)
    QTest.mousePress(card, Qt.LeftButton, pos=QPoint(120, 30))
    QTest.mouseRelease(card, Qt.LeftButton, pos=QPoint(180, 30))
    assert opened.count() == 0
    QTest.mouseClick(card, Qt.LeftButton, pos=QPoint(120, 30))
    assert opened.count() == 1
    card.set_metrics("22.5 °C · 48%")
    assert card._sub_label.text() == "22.5 °C · 48%"
    card.close()
    card.deleteLater()


def test_hiding_tile_only_releases_its_own_gesture(card, state):
    state.refresh()
    state.editing = True  # another surface owns the gesture
    card.hide()
    assert state.editing
    state.editing = False
    card.show()
    card._begin_edit()
    assert state.editing
    card.hide()
    assert not state.editing


def test_presence_failure_cancels_only_ongoing_local_slider_gesture(card, state):
    state.refresh()
    QTest.mousePress(card._slider, Qt.LeftButton, pos=QPoint(80, 20))
    assert state.editing
    state.presence_known = False
    state.changed.emit()
    assert not state.editing
    assert not card._slider.isSliderDown()
    assert not state.service.writes


@pytest.fixture
def enum_fan(qapp):
    state = QuickControlSession(FAN, FakeService(), ImmediateJobs())
    state._loaded = True
    prop = PropInfo("fan-level", "风速", "uint8", True, True, value_list=[
        {"value": 2, "description": "轻风"},
        {"value": 8, "description": "标准"},
        {"value": 31, "description": "强风"},
    ], semantic_name="fan-level", service_name="fan")
    state.props = [prop]
    state.values = {prop.name: 8}
    state.service.by_device[FAN.did][prop.name] = 8
    card = DeviceCard(FAN, session=state)
    card.show()
    qapp.processEvents()
    yield state, card
    state._send_timer.stop()
    state._confirm_timer.stop()
    card.close()
    card.deleteLater()
    state.deleteLater()


def test_fan_sparse_enum_segments_match_published_order(enum_fan):
    state, card = enum_fan
    assert card._slider.isEnabled()
    assert card._slider.minimum() == 0
    assert card._slider.maximum() == 2
    assert card._slider.value() == 1
    assert card._slider.segments == ("轻风", "标准", "强风")
    assert card._sub_label.text() == "风速 标准"


def test_enum_slider_release_writes_original_value_and_never_index(enum_fan):
    state, card = enum_fan
    slider = card._slider
    opened = QSignalSpy(card.open_requested)
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(80, 20))
    QTest.mouseMove(slider, QPoint(slider.width() - 3, 20))
    assert not state.service.writes
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(slider.width() - 3, 20))
    assert state.requested == ("fan-level", 31)
    QTest.qWait(210)
    assert state.service.writes == [(FAN.did, "fan-level", 31)]
    assert opened.count() == 0


def test_unknown_enum_value_disables_instead_of_selecting_first(enum_fan):
    state, card = enum_fan
    state.values["fan-level"] = 99
    state.changed.emit()
    assert not card._slider.isEnabled()
    assert card._slider.isUnknown()
    assert card._slider.value() == 1  # retain previous index without painting any selection
    assert card._sub_label.text() == "档位未知"
    card._commit_value()
    assert state.requested is None
    assert not state.service.writes


def test_string_enum_maps_to_original_string(enum_fan):
    state, card = enum_fan
    state.props = [PropInfo("fan-level", "风速", "string", True, True, value_list=[
        {"value": "breeze", "description": "轻风"},
        {"value": "turbo", "description": "强风"},
    ], service_name="fan", semantic_name="fan-level")]
    state.values["fan-level"] = "turbo"
    state.changed.emit()
    assert card._slider.maximum() == 1
    assert card._slider.value() == 1
    assert card._sub_label.text() == "风速 强风"
    card._slider.setValue(0)
    card._commit_value()
    assert state.requested == ("fan-level", "breeze")


def test_small_stepped_fan_range_is_segmented(enum_fan):
    state, card = enum_fan
    state.props = [PropInfo("fan-level", "风速", "uint8", True, True, (2, 8, 2),
                            service_name="fan", semantic_name="fan-level")]
    state.values["fan-level"] = 6
    state.changed.emit()
    assert card._slider.maximum() == 3
    assert card._slider.value() == 2
    assert card._slider.segments == ("2", "4", "6", "8")
    card._slider.setValue(1)
    card._commit_value()
    assert state.requested == ("fan-level", 4)
