# SPDX-License-Identifier: GPL-3.0-or-later
"""Single relay switches expose power without selecting the indicator LED."""
from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy

from app.core import _json_store, tray_store
from app.core.models import DeviceDetail, DeviceInfo, PropInfo
from app.core.quick_controls import select_quick_props, supports_quick_controls
from app.core.service import MijiaService
from app.ui.tray.device_controls import QuickDeviceCard
from app.ui.tray.quick_window import TrayQuickWindow
from tests.test_quick_controls import FakeService, ImmediateJobs


SWITCH = DeviceInfo("test-switch", "吸顶灯", "zimi.switch.dhkg01", "家", "卧室", True,
                    "urn:miot-spec-v2:device:switch:0000A003:zimi-dhkg01:3:0000C808")
RELAY = PropInfo("on-2", "按键", "bool", True, True,
                 semantic_name="on", service_name="switch")
LED = replace(RELAY, name="on-10", desc="指示灯", service_name="indicator-light")
MODE = PropInfo("mode", "有线/无线模式", "uint8", True, True,
                value_list=[{"value": 0}, {"value": 1}],
                semantic_name="mode", service_name="switch")


class SwitchService(FakeService):
    def __init__(self):
        super().__init__()
        self.by_device[SWITCH.did] = {RELAY.name: False, LED.name: True, MODE.name: 0}

    def device_detail(self, did):
        return DeviceDetail(did, SWITCH.name, SWITCH.model, [LED, MODE, RELAY], [])


@pytest.mark.parametrize("props", [[LED, MODE, RELAY], [RELAY, MODE, LED]])
def test_switch_power_excludes_indicator_and_wireless_mode(props):
    assert supports_quick_controls(SWITCH)
    assert supports_quick_controls(replace(SWITCH, model="other.device"))
    assert select_quick_props(props) == [RELAY]
    flattened = [{"name": p.name, "type": p.type, "rw": "rw",
                  "semantic_name": p.semantic_name, "service_name": p.service_name,
                  "method": {"siid": 2 if p is RELAY else 10, "piid": 1}}
                 for p in props if p is not MODE]
    assert MijiaService._find_on_method({"properties": flattened}) == {"siid": 2, "piid": 1}


def test_multiple_relays_do_not_become_an_ambiguous_master_switch():
    other = replace(RELAY, name="on-3")
    assert not select_quick_props([LED, RELAY, other, MODE])


def test_tray_switch_appears_after_read_and_controls_only_relay(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(_json_store, "data_file", lambda name: tmp_path / name)
    monkeypatch.setattr(_json_store, "data_dir", lambda: tmp_path)
    tray_store.save([SWITCH.did])
    service = SwitchService()
    tray = TrayQuickWindow(service, ImmediateJobs())
    try:
        tray._registry.confirm_presence([SWITCH])
        tray.set_devices([SWITCH], {})  # No cached power state at initial creation.
        tray._rebuild()
        cards = tray.findChildren(QuickDeviceCard)
        assert len(cards) == 1
        card = cards[0]
        state = card.session
        assert card._power.isHidden()
        state.refresh()
        assert not card._power.isHidden() and card._power.isEnabled()
        assert card._power.state() is False
        opened = QSignalSpy(card.open_details)
        card._power.click()
        state._send_timer.stop()
        state._send_write()
        assert service.writes == [(SWITCH.did, RELAY.name, True)]
        assert service.by_device[SWITCH.did][LED.name] is True
        assert opened.count() == 0
        state._confirm_timer.stop()
        state._read()
        assert card._power.state() is True and not state.busy
        service.by_device[SWITCH.did][RELAY.name] = False
        state.refresh()
        assert card._power.state() is False
        state.update_device(replace(SWITCH, online=False))
        assert not card._power.isEnabled()
    finally:
        for state in tray._registry.sessions.values():
            state._send_timer.stop()
            state._confirm_timer.stop()
        tray.close()
        tray.deleteLater()
