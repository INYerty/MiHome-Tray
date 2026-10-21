# SPDX-License-Identifier: GPL-3.0-or-later
"""Render real widgets against simulated devices; no account access or writes."""
import math
from dataclasses import replace
from pathlib import Path
import tempfile

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from app.core import _json_store, settings_store, tray_store, workbench_store
from app.core.models import DeviceInfo
from app.ui.theme_service import apply_theme
from tests.test_dashboard_upgrade import DashboardService, SPEAKER, ROUTER
from tests.test_quick_controls import LAMP, FAN


class PreviewService(DashboardService):
    def __init__(self):
        super().__init__()
        self.by_device[FAN.did]["fan-level"] = 2

    def device_detail(self, did):
        detail = super().device_detail(did)
        if did == FAN.did:
            detail.props = [replace(prop, range=None, value_list=[
                {"value": 1, "description": "一档"}, {"value": 2, "description": "二档"},
                {"value": 3, "description": "三档"}]) if prop.name == "fan-level" else prop for prop in detail.props]
        return detail


def main():
    app = QApplication.instance() or QApplication([])
    # Qt's offscreen platform does not enumerate Windows system fonts.
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{filename}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setQuitOnLastWindowClosed(False)
    from app import __version__
    output = Path(__file__).resolve().parents[1] / "artifacts" / f"v{__version__}"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mihome-preview-") as temporary:
        _json_store.data_file = lambda name: Path(temporary) / name
        _json_store.data_dir = lambda: Path(temporary)
        settings_store.set_theme_mode("dark")
        settings_store.set_tray_size(430, 740)
        settings_store.set_speaker_commands(SPEAKER.did, [
            {"title": "晚安", "text": "关闭卧室灯"},
            {"title": "客厅舒适模式", "text": "打开客厅风扇"},
        ])
        workbench_store.save(SPEAKER.did, ["action:execute-text-directive"])
        devices = [LAMP, FAN, SPEAKER, ROUTER,
                   DeviceInfo("test-temp", "温湿度传感器", "xiaomi.sensor.test", "家", "卧室", True),
                   DeviceInfo("test-offline", "阳台插座", "xiaomi.plug.test", "家", "阳台", False)]
        tray_store.save([device.did for device in devices[:4]])
        apply_theme("dark")
        import app.ui.main_window as main_module
        main_module.MijiaService = PreviewService
        for method in ("_refresh_power_states", "_refresh_metrics", "_load_card_icons", "_load_scenes", "_refresh_presence"):
            setattr(main_module.MainWindow, method, lambda *args, **kwargs: None)
        window = main_module.MainWindow()
        window._default_size_applied = True
        window._known_power = {LAMP.did: True, FAN.did: True}
        window.resize(1050, 680)
        window._apply_devices(devices)
        window.show()
        app.processEvents()
        window._rebuild_grid()
        window._main_controls.confirm_presence(devices)
        window._refresh_card_controls()
        QTest.qWait(300)
        window.grab().save(str(output / "dashboard.png"))
        quick = window._tray._quick
        quick._install_outside_filter = lambda: None
        quick._registry.confirm_presence(devices)
        quick._jobs = __import__("tests.test_quick_controls", fromlist=["ImmediateJobs"]).ImmediateJobs()
        quick.show_near_tray()
        QTest.qWait(300)
        quick.grab().save(str(output / "quick-devices.png"))
        # The grouped-control preview matches a lamp/fan/router collection.
        # Preference and account fixtures remain confined to this temp directory.
        tray_store.save([device.did for device in (LAMP, FAN, ROUTER)])
        quick.set_devices([LAMP, FAN, ROUTER], {})
        QTest.qWait(150)
        quick.grab().save(str(output / "grouped-controls.png"))
        tray_store.save([device.did for device in devices[:4]])
        quick.set_devices(devices, {})
        quick._open_inline(SPEAKER.did)
        QTest.qWait(200)
        quick.grab().save(str(output / "quick-speaker.png"))
        quick._open_inline(ROUTER.did)
        QTest.qWait(200)
        from app.ui.router_panel import RouterPanel
        panel = quick._detail_scroll.widget().findChild(RouterPanel)
        for graph in panel._graphs.values():
            for index in range(60):
                graph.append(100 + index * 5, 500000 + 400000 * math.sin(index / 4) ** 2)
        QTest.qWait(120)
        quick.grab().save(str(output / "quick-router.png"))
        quick.abort_toggle_animation()
        quick.hide()
        window._force_quit = True
        window.close()
        app.processEvents()
    print(f"Rendered simulated-device previews: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
