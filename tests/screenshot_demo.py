# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive screenshots of production widgets with isolated demo devices.

No account is opened, no network request is made, no user settings are read.
Capture the two named windows with the desktop screenshot tool for README.
"""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

from app.core import _json_store, tray_store
from app.core.models import PropInfo
from app.ui.theme_service import apply_theme
from tests.test_quick_controls import FakeService, ImmediateJobs, LAMP, FAN


def main():
    temp = TemporaryDirectory(prefix="mihome-readme-")
    _json_store.data_dir = lambda: Path(temp.name)
    app = QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 9))
    apply_theme("dark")
    lamp = replace(LAMP, name="屏幕挂灯 · 演示", home_name="演示家庭")
    fan = replace(FAN, name="落地扇 · 演示", home_name="演示家庭")
    devices = [lamp, fan]
    service = FakeService()
    service.values.update(brightness=70, **{"color-temperature": 4000})
    service.by_device[FAN.did].update({"fan-level": 2, "horizontal-swing": True})
    detail = service.device_detail
    def device_detail(did):
        result = detail(did)
        if did == FAN.did:
            result.props[1] = PropInfo("fan-level", "风速", "uint8", True, True,
                value_list=[{"value": n, "description": f"{n} 挡"} for n in (1, 2, 3)])
        return result
    service.device_detail = device_detail
    service.list_devices = lambda: devices
    for name in ("read_metrics", "power_states", "icon_urls", "localized_product_names"):
        setattr(service, name, lambda *args, **kwargs: {})
    service.spec_has_published_functions = lambda *_: True
    tray_store.save([lamp.did, fan.did])
    from app.ui.main_window import MainWindow
    with patch("app.ui.main_window.MijiaService", return_value=service):
        window = MainWindow()
    window.setWindowTitle("MiHome Tray · 主页面演示")
    window.setWindowFlags(window.windowFlags() | Qt.WindowStaysOnTopHint)
    window._default_size_applied = True
    window.resize(820, 520)
    window.move(150, 120)
    for name in ("_refresh_power_states", "_refresh_metrics", "_load_card_icons", "_load_scenes"):
        setattr(window, name, lambda *args, **kwargs: None)
    window._known_power = {lamp.did: True, fan.did: True}
    backdrop = QWidget()
    backdrop.setWindowTitle("MiHome Tray · 效果图背景")
    backdrop.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #32404d,stop:0.45 #547580,stop:1 #56617e);")
    backdrop.resize(1400, 850)
    backdrop.move(60, 60)
    backdrop.show()
    window.show()
    window._apply_devices(devices)
    quick = window._tray._quick
    quick.setWindowTitle("MiHome Tray · 托盘演示")
    quick.setWindowFlags((quick.windowFlags() & ~Qt.Tool) | Qt.Window)
    quick._install_outside_filter = lambda: None
    quick._jobs = ImmediateJobs()
    quick._registry.jobs = quick._jobs
    quick._registry.confirm_presence(devices)
    quick.show_near_tray()
    # Real production widgets; only the demo layout is positioned for export.
    QTimer.singleShot(350, lambda: quick.move(1020, 135))
    print("Demo windows ready; only synthetic data is present", flush=True)
    result = app.exec()
    window.request_force_quit()
    temp.cleanup()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
