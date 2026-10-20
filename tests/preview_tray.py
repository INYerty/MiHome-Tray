# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the actual flyout with simulated devices, no account or network."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

from app.core import tray_store, settings_store
from app.ui.theme_service import apply_theme
from app.ui.tray.quick_window import TrayQuickWindow
from tests.test_quick_controls import FakeService, ImmediateJobs, LAMP, FAN


def main():
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setQuitOnLastWindowClosed(False)
    apply_theme("dark")
    # Patch stores only in this process. Never write sample devices to user data.
    tray_store.load = lambda: [LAMP.did, FAN.did]
    tray_store.load_scenes = lambda: []
    tray_store.load_order = lambda: [{"type": "device", "id": d.did} for d in (LAMP, FAN)]
    settings_store.get_tray_columns = lambda: 1
    service = FakeService()
    window = TrayQuickWindow(service, ImmediateJobs())
    if "--interactive" in sys.argv:
        window._install_outside_filter = lambda: None  # keep this test fixture visible
        window.setWindowFlags((window.windowFlags() & ~Qt.Tool) | Qt.Window)
    background = None
    if "--glass-check" in sys.argv:
        background = QWidget()
        background.setWindowTitle("毛玻璃渲染测试背景")
        background.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #fa8434,stop:0.5 #3665f0,stop:1 #24d4b0);")
        background.resize(700, 700)
        background.move(250, 100)
        background.show()
    window.setWindowTitle("米家快捷控制 · 模拟设备预览")
    window._registry.confirm_presence([LAMP, FAN])
    window.set_devices([LAMP, FAN], {LAMP.did: True, FAN.did: True})
    window.show_near_tray()
    if background is not None:
        QTimer.singleShot(350, lambda: window.move(400, 180))
    output = Path(__file__).resolve().parents[1] / "artifacts"
    output.mkdir(exist_ok=True)

    def capture():
        window.grab().save(str(output / "tray-preview.png"))
        print("Preview saved: " + str(output / "tray-preview.png"), flush=True)
        print(f"Native glass active: {window.property('glassActive')}; alpha: {window.windowHandle().format().alphaBufferSize()}", flush=True)
        if "--interactive" not in sys.argv:
            window.hide()
            app.quit()

    QTimer.singleShot(800, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
