# SPDX-License-Identifier: GPL-3.0-or-later
"""Behavior checks use simulated devices; they do not access an account."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from app.core.models import DeviceDetail, DeviceInfo, PropInfo
from app.core.quick_controls import QuickControlSession, select_quick_props
from app.core.secure_api import SecureMijiaAPI, protect


LAMP = DeviceInfo("test-lamp", "示例挂灯", "yeelink.light.test", "家", "书房", True)
FAN = DeviceInfo("test-fan", "示例落地扇", "dmaker.fan.test", "家", "客厅", True)
LIGHT_PROPS = [
    PropInfo("on", "开关", "bool", True, True),
    PropInfo("brightness", "亮度", "uint8", True, True, (1, 100, 1)),
    PropInfo("color-temperature", "色温 / K", "uint32", True, True, (2700, 6500, 100)),
]
FAN_PROPS = [
    PropInfo("on", "开关", "bool", True, True),
    PropInfo("fan-level", "风速", "uint8", True, True, (1, 100, 1)),
    PropInfo("mode", "模式", "uint8", True, True, value_list=[
        {"value": 0, "description": "直吹风"}, {"value": 1, "description": "自然风"}]),
    PropInfo("horizontal-swing", "左右摇头", "bool", True, True),
]


class ImmediateJobs:
    def submit(self, fn, on_success=None, on_error=None):
        try:
            result = fn()
        except Exception as error:
            if on_error:
                on_error(error)
            else:
                raise
        else:
            if on_success:
                on_success(result)


class FakeService:
    def __init__(self):
        self.values = {"on": True, "brightness": 50, "color-temperature": 4000,
                       "fan-level": 35, "mode": 0, "horizontal-swing": False}
        self.by_device = {LAMP.did: self.values, FAN.did: dict(self.values)}
        self.writes = []
        self.apply_writes = True
        self.fail_read = False

    def device_detail(self, did):
        props = LIGHT_PROPS if did == LAMP.did else FAN_PROPS
        return DeviceDetail(did, "示例设备", "test", props, [])

    def read_props(self, did, names):
        if self.fail_read:
            raise ConnectionError("模拟网络断开")
        return {name: self.by_device[did].get(name) for name in names}

    def write_prop(self, did, name, value):
        self.writes.append((did, name, value))
        if self.apply_writes:
            self.by_device[did][name] = value


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def session(qapp):
    model = QuickControlSession(LAMP, FakeService(), ImmediateJobs())
    model.refresh()
    yield model
    model._send_timer.stop()
    model._confirm_timer.stop()
    model.deleteLater()


def test_only_published_writable_capabilities_are_shown():
    readonly = PropInfo("speed", "电机转速", "uint32", True, False, (0, 2000, 1))
    unsupported = PropInfo("dangerous-reset", "重置", "bool", True, True)
    result = select_quick_props([*LIGHT_PROPS, readonly, unsupported])
    assert [p.name for p in result] == ["on", "brightness", "color-temperature"]


def test_duplicate_power_names_use_fan_service_and_exclude_indicator():
    fan_power = PropInfo("on-2", "风扇电源", "bool", True, True,
                         semantic_name="on", service_name="fan")
    led = PropInfo("on-5", "指示灯", "bool", True, True,
                   semantic_name="on", service_name="indicator-light")
    indicator = PropInfo("brightness", "指示灯", "bool", True, True,
                         semantic_name="brightness", service_name="fan")
    result = select_quick_props([led, indicator, fan_power, FAN_PROPS[1]])
    assert [p.name for p in result] == ["on-2", "fan-level"]


def test_quick_power_never_selects_indicator_when_spec_order_changes():
    from app.core.service import MijiaService
    led = {"name": "on-5", "semantic_name": "on", "service_name": "indicator-light",
           "type": "bool", "rw": "rw", "method": {"siid": 5, "piid": 1}}
    fan = {"name": "on-2", "semantic_name": "on", "service_name": "fan",
           "type": "bool", "rw": "rw", "method": {"siid": 2, "piid": 1}}
    for props in ([led, fan], [fan, led]):
        assert MijiaService._find_on_method({"properties": props}) == fan["method"]
    no_context = [{k: v for k, v in p.items() if k not in ("semantic_name", "service_name")} for p in (led, fan)]
    assert MijiaService._find_on_method({"properties": no_context}) is None


def test_light_panel_does_not_require_optional_scene_reading():
    props = [replace(p, service_name="light", semantic_name=p.name) for p in LIGHT_PROPS]
    props.append(PropInfo("mode", "场景", "uint", True, True,
                          value_list=[{"value": 5, "description": "阅读"}],
                          semantic_name="mode", service_name="light"))
    assert [p.name for p in select_quick_props(props)] == ["on", "brightness", "color-temperature"]


def test_last_slider_intent_is_sent_once_and_requires_confirmation(session):
    session.request_write("brightness", 60)
    session.request_write("brightness", 85)
    session._send_timer.stop()
    session._send_write()
    assert session.service.writes == [(LAMP.did, "brightness", 85)]
    assert session.busy and session.values["brightness"] == 50
    session._confirm_timer.stop()
    session._read()
    assert not session.busy and session.values["brightness"] == 85
    assert session.message == "回读已确认"


def test_accepted_command_with_unchanged_state_is_not_reported_success(session):
    session.service.apply_writes = False
    session.request_write("on", False)
    session._send_timer.stop()
    session._send_write()
    for _ in range(3):
        session._confirm_timer.stop()
        session._read()
    assert session.error and not session.busy
    assert "未确认生效" in session.message
    assert session.values["on"] is True


def test_failed_read_can_recover_and_phone_change_is_observed(session):
    session.service.fail_read = True
    session.refresh()
    assert session.error
    session.service.fail_read = False
    session.service.values["brightness"] = 12  # another client changes the device
    session.refresh()
    assert not session.error
    assert session.values["brightness"] == 12


def test_partial_failure_does_not_permanently_remove_control(session):
    session.service.values["brightness"] = None
    session.refresh()
    assert session.error and session.values["brightness"] is None
    session.service.values["brightness"] = 48
    session.refresh()
    assert not session.error and session.values["brightness"] == 48


def test_offline_device_does_not_use_cached_cloud_value_as_confirmation(session):
    session.update_device(replace(LAMP, online=False))
    session.request_write("on", False)
    session.refresh()
    assert session.service.writes == []
    assert session.error
    session.update_device(replace(LAMP, online=True))
    session.service.values["on"] = False
    session.refresh()
    assert session.values["on"] is False and not session.error


def test_unpublished_out_of_range_and_off_step_values_are_not_sent(session):
    for name, value in [("reset", True), ("brightness", 101), ("color-temperature", 2725), ("on", 1)]:
        session.request_write(name, value)
    assert not session._send_timer.isActive()
    assert session.service.writes == []


def test_favorites_are_polled_across_room_filters_and_after_unknown(qapp):
    from app.ui.main_window import MainWindow
    from app.core import tray_store
    from unittest.mock import patch

    batches = []
    obj = SimpleNamespace(_poll_in_flight=False, _all_devices=[LAMP, FAN],
                          _visible_devices=lambda: [LAMP], _known_power={LAMP.did: True, FAN.did: None},
                          _service=SimpleNamespace(power_states=lambda dids: batches.append(dids) or {}),
                          _jobs=ImmediateJobs(), _apply_power_states=lambda _: None, _on_poll_error=lambda _: None)
    with patch.object(tray_store, "load", return_value=[FAN.did]):
        MainWindow._refresh_power_states(obj, force=True)
    assert batches == [[LAMP.did, FAN.did]]


def test_dpapi_roundtrip_never_writes_plaintext_credentials(tmp_path):
    secret = b"synthetic-test-session-only"
    assert protect(protect(secret), decrypt=True) == secret
    path = tmp_path / "account.dpapi"
    api = SecureMijiaAPI(path)
    api.auth_data = {"synthetic": "not-a-real-token", "ssecurity": "synthetic",
                     "cUserId": "test", "serviceToken": "test", "userId": "test"}
    api._save_auth_data()
    assert b"not-a-real-token" not in path.read_bytes()
    assert not (tmp_path / "auth.json").exists()
    assert SecureMijiaAPI(path).auth_data["synthetic"] == "not-a-real-token"


def test_polling_does_not_interrupt_slider_drag(session):
    stamp = session.updated_at
    session.editing = True
    session.service.values["brightness"] = 75
    session.refresh()
    assert session.updated_at == stamp and session.values["brightness"] == 50
    session.editing = False
    session.refresh()
    assert session.values["brightness"] == 75


def test_uncertain_presence_does_not_turn_cached_reads_into_online_state(qapp):
    from app.core.quick_controls import QuickControlRegistry
    registry = QuickControlRegistry(FakeService(), ImmediateJobs())
    model = registry.session(LAMP)
    model.refresh()
    assert not model.presence_known and not model.values
    registry.confirm_presence([LAMP])
    model.refresh()
    assert model.values["brightness"] == 50
    registry.presence_failed()
    model.request_write("on", False)
    assert not model._send_timer.isActive()
    registry.confirm_presence([replace(LAMP, online=False)])
    assert not model.device.online
    presence_requests = []
    model.presence_requested.connect(lambda: presence_requests.append(True))
    for _ in range(3):
        registry.refresh([LAMP.did])
    assert not presence_requests  # offline polling must not create a tight retry loop
    model.retry()
    assert presence_requests == [True]
    registry.confirm_presence([LAMP])
    model.refresh()
    assert model.presence_known and model.device.online and not model.error


def test_each_device_has_independent_property_state(qapp):
    service = FakeService()
    service.write_prop(FAN.did, "on", False)
    assert service.read_props(LAMP.did, ["on"])["on"] is True
    assert service.read_props(FAN.did, ["on"])["on"] is False


def test_widgets_reflect_external_updates_without_recreation(session):
    from app.ui.tray.device_controls import QuickDeviceCard
    card = QuickDeviceCard(session)
    slider = card._controls["brightness"][1]
    session.service.values["brightness"] = 88
    session.refresh()
    assert card._controls["brightness"][1] is slider and slider.value() == 87
    card.deleteLater()


def test_tray_power_button_submits_the_requested_state(session):
    from app.ui.tray.device_controls import QuickDeviceCard
    card = QuickDeviceCard(session)
    button = card._controls["on"][1]
    button.click()
    session._send_timer.stop()
    session._send_write()
    assert session.service.writes == [(LAMP.did, "on", False)]
    session._confirm_timer.stop()
    session._read()
    assert button.text() == "已关闭" and not button.isChecked()
    card.deleteLater()


def test_windowed_startup_can_import_protocol_library_without_console(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    code = (
        "import sys; sys.stdout=None; sys.stderr=None; "
        "from app.core.bootstrap import ensure_gui_streams; ensure_gui_streams(); "
        "import mijiaAPI; assert hasattr(mijiaAPI, 'mijiaAPI')"
    )
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path)
    result = subprocess.run([sys.executable, "-c", code], env=env,
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_slider_tracks_pointer_immediately_and_commits_only_on_release(qapp):
    from app.ui.prop_widgets import SliderSection
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    writes = []
    section = SliderSection(LIGHT_PROPS[2], writes.append)
    section.resize(420, 140)
    section.show()
    qapp.processEvents()
    slider = section._slider
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(30, 13))
    QTest.mouseMove(slider, QPoint(slider.width() - 30, 13))
    position = slider.value()
    assert position > slider.maximum() * 0.8 and not writes
    section.refresh_value(2700)  # cloud polling cannot pull an active drag back
    assert slider.value() == position
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(slider.width() - 30, 13))
    assert len(writes) == 1 and (writes[0] - 2700) % 100 == 0
    assert writes[0] > 6000
    section.close()


def test_tray_slider_does_not_get_disabled_by_background_refresh_during_drag(session):
    from app.ui.tray.device_controls import QuickDeviceCard
    card = QuickDeviceCard(session)
    slider = card._controls['brightness'][1]
    slider.setSliderDown(True)
    slider.setValue(76)
    session._inflight = True
    session.changed.emit()
    assert slider.isEnabled() and slider.value() == 76
    slider.setSliderDown(False)
    session._inflight = False
    card.deleteLater()


def test_new_drag_supersedes_pending_confirmation_without_thumb_jump(session):
    from app.ui.tray.device_controls import QuickDeviceCard
    card = QuickDeviceCard(session)
    slider = card._controls['brightness'][1]
    session.request_write('brightness', 70)
    session._send_timer.stop()
    session._send_write()
    assert session._confirming == ('brightness', 70)
    assert slider.isEnabled() and slider.value() == 69
    session.request_write('brightness', 90)
    session._send_timer.stop()
    session._send_write()
    assert session.service.writes[-1] == (LAMP.did, 'brightness', 90)
    session._confirm_timer.stop()
    session._read()
    assert session.values['brightness'] == 90 and not session.busy
    assert slider.value() == 89 and session.requested is None
    card.deleteLater()


def test_slider_intent_is_retained_while_an_older_read_is_inflight(session):
    session._inflight = True
    session.request_write('brightness', 82)
    session._send_timer.stop()
    session._send_write()
    assert not session.service.writes and session._pending == ('brightness', 82)
    session._send_timer.stop()
    session._read_done((session.props, dict(session.values)))
    session._send_timer.stop()
    session._send_write()
    assert session.service.writes == [(LAMP.did, 'brightness', 82)]
