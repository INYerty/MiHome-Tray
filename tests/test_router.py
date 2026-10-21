# SPDX-License-Identifier: GPL-3.0-or-later
"""Telemetry checks use spec-shaped fixtures and never access an account."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from app.core.models import DeviceInfo
from app.core.router import (RouterSnapshot, discover_router, property_text,
                             rate_text, rate_value)
from app.core.service import MijiaService
from app.ui.router_panel import RouterPanel


def prop(iid, name, unit=None, access=None):
    return {"iid": iid, "type": f"urn:miot-spec-v2:property:{name}:00000000:test:1",
            "access": access or ["read"], "unit": unit}


def fixture_spec():
    return {"services": [
        {"iid": 2, "type": "urn:miot-spec-v2:service:router:00007864:test:1",
         "properties": [prop(1, "download-speed", "B/s"), prop(2, "upload-speed"),
                        prop(3, "connected-device-number"), prop(4, "ppp-encrypted-password"),
                        prop(5, "max-upload-speed"), prop(6, "link-speed")]},
        {"iid": 3, "type": "urn:miot-spec-v2:service:guest-wifi:00007864:test:1",
         "properties": [prop(1, "download-speed", "MB/s")]},
    ]}


def test_rates_use_actual_router_semantics_and_declared_units():
    caps = discover_router(fixture_spec())
    assert [(p.name, p.unit) for p in caps.rates] == [
        ("download-speed", "B/s"), ("upload-speed", "")]
    assert [p.name for p in caps.attributes] == ["connected-device-number"]
    assert not caps.client_fields
    assert rate_text(caps.rates[0], 2_500_000) == "2.50 MB/s"
    assert "单位未声明" in rate_text(caps.rates[1], 200)
    assert "结构化" in property_text(caps.attributes[0], {"password": "secret"})


@pytest.mark.parametrize("value", [None, True, -1, float("nan"), float("inf"), "bad"])
def test_invalid_rates_are_missing_not_zero(value):
    assert rate_value(value) is None


def test_service_caches_schema_and_preserves_missing_property(monkeypatch):
    calls = []
    monkeypatch.setattr("requests.get", lambda *a, **k: (
        calls.append(k), SimpleNamespace(raise_for_status=lambda: None, json=fixture_spec))[1])
    service = MijiaService.__new__(MijiaService)
    service._device_index = {"router": ("xiaomi.router.test", "spec:test", "router")}
    queries = []
    def read(batch):
        queries.extend(batch)
        return [{"siid": 2, "piid": 1, "code": 0, "value": 10},
                {"siid": 2, "piid": 2, "code": -1}]
    service._api = SimpleNamespace(get_devices_prop=read)
    one = service.router_snapshot("router")
    two = service.router_snapshot("router")
    assert len(calls) == 1
    assert one.values["2.1"] == 10 and one.values["2.2"] is None
    assert two.timestamp >= one.timestamp
    assert {(q["siid"], q["piid"]) for q in queries} == {(2, 1), (2, 2), (2, 3)}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class DeferredJobs:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, on_success=None, on_error=None):
        self.tasks.append((fn, on_success, on_error))


def test_visible_only_polling_single_pending_bounded_history(qapp):
    caps = discover_router(fixture_spec())
    snapshot = RouterSnapshot(caps, {"2.1": 10, "2.2": None, "2.3": 3}, 100)
    service = SimpleNamespace(router_snapshot=lambda _: snapshot)
    jobs = DeferredJobs()
    device = DeviceInfo("router", "路由器", "xiaomi.router.test", "家", "客厅", True)
    panel = RouterPanel(service, jobs, device)
    panel.refresh()
    assert not jobs.tasks
    panel.show()
    qapp.processEvents()
    panel.refresh()
    assert len(jobs.tasks) == 1
    jobs.tasks.pop()[1](snapshot)
    graph = panel._graphs["2.1"]
    for index in range(100):
        graph.append(index, index)
    assert len(graph.samples) == 60
    panel.hide()
    assert not panel._timer.isActive()
    panel.refresh()
    assert not jobs.tasks
    panel.deleteLater()
