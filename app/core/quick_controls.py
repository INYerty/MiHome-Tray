# SPDX-License-Identifier: GPL-3.0-or-later
"""Tray device state: capabilities come from spec; writes require readback."""

from datetime import datetime
from dataclasses import replace
from math import isclose

from PySide6.QtCore import QObject, QTimer, Signal

from app.core.models import DeviceInfo, PropInfo


def supports_quick_controls(device: DeviceInfo) -> bool:
    return any(part in device.model for part in (".light.", ".fan.", ".switch.")) or any(
        part in device.spec_type for part in (":light:", ":fan:", ":switch:")
    )


def select_quick_props(props: list[PropInfo]) -> list[PropInfo]:
    # Match published semantic names only. Never guess siid/piid or value ranges.
    groups = (
        ("on",), ("brightness",), ("color-temperature",),
        ("fan-level", "speed-level", "wind-speed", "speed"),
        ("mode", "wind-mode"),
        ("horizontal-swing", "swing-mode", "oscillate"),
        ("vertical-swing",),
    )
    switch_power = [p for p in props if p.readable and p.writable and p.type == "bool"
                    and p.service_name == "switch"
                    and (p.semantic_name or p.name.replace("_", "-")) == "on"]
    by_name = {}
    for prop in props:
        if not prop.readable or not prop.writable:
            continue
        if prop.service_name and prop.service_name not in ("light", "fan", "switch"):
            continue
        name = prop.semantic_name or prop.name.replace("_", "-")
        if prop.service_name == "switch" and (len(switch_power) != 1 or prop is not switch_power[0]):
            continue  # Only expose an unambiguous relay, never wireless-mode settings.
        if name == "brightness" and prop.type == "bool":
            continue  # a fan's indicator LED is not light brightness
        if name in ("mode", "wind-mode") and prop.service_name == "light":
            continue  # light scenes are optional; keep the common panel focused
        by_name.setdefault(name, prop)
    result = []
    for alternatives in groups:
        for name in alternatives:
            p = by_name.get(name)
            if p is not None and (p.type == "bool" or p.value_list or p.range):
                result.append(p)
                break
    return result


def values_equal(actual, requested) -> bool:
    if actual is None:
        return False
    if isinstance(requested, bool):
        return actual in (0, 1, False, True) and bool(actual) == requested
    if isinstance(actual, (int, float)) and isinstance(requested, (int, float)):
        return isclose(actual, requested, abs_tol=1e-6)
    return actual == requested


class QuickControlSession(QObject):
    """One state owner per device, retained when the flyout widgets rebuild."""

    changed = Signal()
    presence_requested = Signal()

    def __init__(self, device, service, jobs, parent=None):
        super().__init__(parent)
        self.device = device
        self.presence_known = True
        self.service = service
        self.jobs = jobs
        self.props: list[PropInfo] = []
        self.values: dict = {}
        self.updated_at: datetime | None = None
        self.message = "等待读取" if device.online else "设备离线"
        self.error = False
        self.busy = False
        self._loaded = False
        self.editing = False
        self._inflight = False
        self._pending: tuple | None = None
        self.requested: tuple | None = None
        self._confirming: tuple | None = None
        self._attempts = 0
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.setInterval(180)
        self._send_timer.timeout.connect(self._send_write)
        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self._read)

    def update_device(self, device):
        previous = self.device.online
        self.device = device
        if not device.online:
            self.message = "设备离线"
            self.error = True
        elif not previous:
            self.message = "设备已重新上线，等待读取"
            self.error = False
        self.changed.emit()

    def refresh(self):
        if self._inflight or self.busy or self.editing:
            return
        if not self.device.online or not self.presence_known:
            return
        self._read()

    def retry(self):
        if not self.device.online or not self.presence_known:
            self.presence_requested.emit()
        else:
            self._loaded = False  # also retry metadata after a spec lookup failure
            self.refresh()

    def _read(self):
        if self._inflight:
            return
        if not self.device.online:
            self._failed(RuntimeError("设备离线"))
            return
        self._inflight = True
        if not self._confirming:
            self.message = "正在同步…"
        self.changed.emit()

        def fetch():
            props = self.props if self._loaded else select_quick_props(
                self.service.device_detail(self.device.did).props)
            values = self.service.read_props(self.device.did, [p.name for p in props]) if props else {}
            return props, values

        self.jobs.submit(fetch, on_success=self._read_done, on_error=self._failed)

    def _read_done(self, result):
        self._inflight = False
        if not self.device.online:
            self._failed(RuntimeError("设备离线"))
            return
        self.props, values = result
        self._loaded = True
        # Missing/failed properties become unknown, never retain them as fresh.
        self.values = {p.name: values.get(p.name) for p in self.props}
        if any(v is not None for v in self.values.values()):
            self.updated_at = datetime.now()
        self.error = any(v is None for v in self.values.values())
        if self._pending:
            # A newer drag supersedes the previous command's confirmation.
            # The serial job has finished; submit only the latest intent next.
            self._confirming = None
            self._confirm_timer.stop()
            self.message = "准备设置最新值…"
            self._send_timer.start(0)
        elif self._confirming:
            name, target = self._confirming
            if values_equal(self.values.get(name), target):
                self.message = "回读已确认"
                self._confirming = None
                self.busy = False
                self.requested = None
            elif self._attempts < 2:
                self._attempts += 1
                self.message = "等待设备确认…"
                self._confirm_timer.start(1000 * self._attempts)
            else:
                self.message = "未确认生效，已显示回读状态"
                self.error = True
                self._confirming = None
                self.busy = False
                self.requested = None
        else:
            self.message = ("部分状态读取失败，可重试" if self.error else
                            "已同步" if self.props else "常用功能未识别，请打开详情")
        if not self.presence_known:
            self.message += " · 在线状态待确认"
        self.changed.emit()

    def request_write(self, name, value):
        if not self.device.online or not self.presence_known:
            return
        prop = next((p for p in self.props if p.name == name), None)
        if prop is None or self.values.get(name) is None:
            return
        if prop.type == "bool":
            if not isinstance(value, bool):
                return
        elif prop.value_list:
            if value not in [v["value"] for v in prop.value_list]:
                return
        elif prop.range:
            lo, hi, step = prop.range
            if not isinstance(value, (int, float)) or not lo <= value <= hi:
                return
            if step > 0 and not isclose((value - lo) / step, round((value - lo) / step), abs_tol=1e-5):
                return
        self._pending = (name, value)  # debounce keeps only the last intent
        self.requested = (name, value)
        self.busy = True
        self.error = False
        self.message = "准备设置…"
        self._send_timer.start()
        self.changed.emit()

    def _send_write(self):
        if self._pending is None:
            return
        if self._inflight:
            self._send_timer.start(100)
            return
        self._confirm_timer.stop()
        self._confirming = None
        name, value = self._pending
        self._pending = None
        if not self.device.online:
            self._failed(RuntimeError("设备离线，未发送指令"))
            return
        self._inflight = True
        self.message = "正在发送，等待确认…"
        self.changed.emit()

        def done(_):
            self._inflight = False
            if self._pending:
                self._send_timer.start(0)
                return
            self._confirming = (name, value)
            self._attempts = 0
            self._confirm_timer.start(700)

        self.jobs.submit(lambda: self.service.write_prop(self.device.did, name, value),
                         on_success=done, on_error=self._failed)

    def _failed(self, error):
        self._send_timer.stop()
        self._confirm_timer.stop()
        self._inflight = False
        self._confirming = None
        self._pending = None
        self.requested = None
        self.busy = False
        self.error = True
        self.message = f"同步或操作失败：{error}"
        self.changed.emit()


class QuickControlRegistry(QObject):
    presence_requested = Signal()

    def __init__(self, service, jobs, parent=None):
        super().__init__(parent)
        self.service, self.jobs = service, jobs
        self.sessions: dict[str, QuickControlSession] = {}
        self.presence_known = False  # disk cache alone cannot establish presence

    def session(self, device):
        if device.did not in self.sessions:
            session = QuickControlSession(device, self.service, self.jobs, self)
            session.presence_known = self.presence_known
            session.presence_requested.connect(self.presence_requested.emit)
            self.sessions[device.did] = session
        return self.sessions[device.did]

    def confirm_presence(self, devices):
        self.presence_known = True
        self.update_devices(devices)
        for session in self.sessions.values():
            session.presence_known = True
            session.changed.emit()

    def presence_failed(self):
        self.presence_known = False
        for session in self.sessions.values():
            session.presence_known = False
            session.message = "在线状态刷新失败，显示上次读数"
            session.error = True
            session.changed.emit()

    def update_devices(self, devices):
        lookup = {d.did: d for d in devices}
        for did, session in self.sessions.items():
            if did in lookup:
                session.update_device(lookup[did])
            else:
                session.update_device(replace(session.device, online=False))
                session.message = "设备已不在当前账号列表中"
                session.changed.emit()

    def refresh(self, dids):
        for did in dids:
            if did in self.sessions:
                self.sessions[did].refresh()
