# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only router telemetry, selected from each account device's MIOT spec.

Only published traffic-rate properties are charted. Port capacity, speed limits,
passwords and action parameters are deliberately outside this view.
"""

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class RouterProperty:
    siid: int
    piid: int
    name: str
    label: str
    unit: str = ""
    choices: tuple = ()

    @property
    def key(self) -> str:
        return f"{self.siid}.{self.piid}"


@dataclass(frozen=True)
class RouterCapabilities:
    rates: tuple[RouterProperty, ...] = ()
    attributes: tuple[RouterProperty, ...] = ()
    client_fields: tuple[RouterProperty, ...] = ()

    @property
    def properties(self) -> tuple[RouterProperty, ...]:
        return self.rates + self.attributes + self.client_fields


@dataclass(frozen=True)
class RouterSnapshot:
    capabilities: RouterCapabilities
    values: dict[str, Any]
    timestamp: float


_ATTRIBUTES = {
    "connected-device-number": "连接设备数", "ip-address": "IP 地址",
    "network-connection-type": "上网方式", "status": "工作状态",
    "online-time": "在线时长", "rssi": "信号强度",
    "gateway-ip-address": "网关", "dns-ip-address": "DNS",
}
_CLIENT_FIELDS = {
    "dev-list-mac": "设备 MAC 列表", "dev-list-rssi": "设备信号列表",
    "dev-list-access-type": "设备接入方式列表",
    "dev-list-up-speed": "设备上传速率列表",
    "dev-list-downspeed": "设备下载速率列表",
    "device-name": "设备名称", "device-ip": "设备 IP", "device-mac": "设备 MAC",
    "device-type": "设备类型", "device-band": "设备品牌", "device-mode": "设备型号",
    "device-internet-type": "设备接入类型",
}


def is_router(device) -> bool:
    return ".router." in device.model or ":device:router:" in device.spec_type


def _semantic(urn: str) -> str:
    parts = urn.split(":")
    return parts[3] if len(parts) > 3 else ""


def discover_router(spec: dict) -> RouterCapabilities:
    rates, attributes, clients = [], [], []
    for service in spec.get("services", []):
        service_name = _semantic(service.get("type", ""))
        for prop in service.get("properties", []):
            if "read" not in prop.get("access", []):
                continue
            name = _semantic(prop.get("type", ""))
            label = ""
            target = None
            if service_name == "router":
                if name in ("download-speed", "upload-speed"):
                    label = "下载" if name == "download-speed" else "上传"
                    target = rates
                elif name in _ATTRIBUTES:
                    label, target = _ATTRIBUTES[name], attributes
            elif service_name in ("device", "device-list") and name in _CLIENT_FIELDS:
                label, target = _CLIENT_FIELDS[name], clients
            if target is None:
                continue
            unit = prop.get("unit") or ""
            if unit == "none":
                unit = ""
            choices = tuple((item.get("value"), item.get("comment") or item.get("description", ""))
                            for item in prop.get("value-list", []))
            target.append(RouterProperty(service["iid"], prop["iid"], name, label, unit, choices))
    return RouterCapabilities(tuple(rates), tuple(attributes), tuple(clients))


def rate_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def property_text(prop: RouterProperty, value: Any) -> str:
    if value is None:
        return "暂未读取到"
    for option, label in prop.choices:
        if option == value:
            return str(label)
    if isinstance(value, (dict, list)):
        # Never expose unknown nested fields (such as secrets) as raw JSON.
        return "设备返回了结构化数据，此型号格式暂不支持"
    text = str(value)[:1000]
    unit = {"minutes": "分钟", "seconds": "秒"}.get(prop.unit, prop.unit)
    return f"{text} {unit}".strip()


def rate_text(prop: RouterProperty, value: Any) -> str:
    number = rate_value(value)
    if number is None:
        return "暂未读取到"
    # Unit case matters: B/s and b/s differ by eight. Keep unknown units explicit.
    if prop.unit == "B/s":
        for factor, label in ((1e9, "GB/s"), (1e6, "MB/s"), (1e3, "kB/s")):
            if number >= factor:
                return f"{number / factor:.2f} {label}"
    return f"{number:g} {prop.unit or '（单位未声明）'}"
