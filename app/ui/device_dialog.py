# SPDX-License-Identifier: GPL-3.0-or-later
# MiHome-Windows: 米家设备的 Windows 桌面控制端
# Copyright (C) 2026 MiHome-Windows contributors
"""设备详情抽屉：与添加功能同款的侧滑抽屉。

不再作为独立窗口弹出，而是以遮罩 + 右侧面板的形式覆盖在主窗口
之上，观感与添加功能抽屉一致；内部直接复用 WorkbenchPanel。
"""

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QTabWidget, QVBoxLayout

from app.core.jobs import JobExecutor
from app.core.models import DeviceInfo, is_speaker
from app.core.router import is_router
from app.core.service import MijiaService
from app.ui.overlay_dialog import OverlayDialog
from app.ui.workbench_panel import WorkbenchPanel
from app.ui.router_panel import RouterPanel
from app.ui.speaker_commands import SpeakerCommands


class DeviceDetailDialog(OverlayDialog):
    def __init__(self, service: MijiaService, jobs: JobExecutor,
                 device: DeviceInfo, parent=None):
        super().__init__(parent)
        self.device = device

        outer = QVBoxLayout(self._panel)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # 顶部标题栏：设备信息已由工作台内部展示，此处仅保留关闭按钮
        header = QHBoxLayout()
        header.addStretch(1)
        header.addWidget(self._make_close_button())
        outer.addLayout(header)

        # 工作台
        self._workbench = WorkbenchPanel(service, jobs, self._panel)
        self._router = None
        self._speaker_commands = None
        if is_router(device):
            tabs = QTabWidget(self._panel)
            self._router = RouterPanel(service, jobs, device, tabs)
            scroll = QScrollArea(tabs)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(self._router)
            tabs.addTab(scroll, "网络概览")
            tabs.addTab(self._workbench, "更多功能")
            outer.addWidget(tabs, stretch=1)
        else:
            if is_speaker(device):
                self._speaker_commands = SpeakerCommands(service, jobs, device, self._panel)
                outer.addWidget(self._speaker_commands)
            outer.addWidget(self._workbench, stretch=1)

    @property
    def panel(self) -> WorkbenchPanel:
        return self._workbench

    def load(self) -> None:
        self._workbench.show_device(self.device.did, online=self.device.online, device=self.device)

    def retheme(self) -> None:
        """主题切换：面板底色 + 工作台头部按钮与功能区块重建。"""
        super().retheme()
        self._workbench.retheme()
        if self._router is not None:
            self._router.retheme()
        if self._speaker_commands is not None:
            self._speaker_commands.retheme()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_overlay()
        # 居中面板：宽度 900，窗口过窄时自适应收缩
        pw = 900
        pw = min(pw, max(320, self.width() - 40))
        ph = min(640, self.height() - 40)
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        self._panel.setGeometry(x, y, pw, ph)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._fill_parent_window():
            self.raise_()
            self._fade_in()
            return
        # 托盘独立弹出：铺满可用屏幕（遮罩盖住全屏，避免只罩一小块、
        # 周围露出桌面壁纸的突兀观感），面板由 resizeEvent 居中放置
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        self.raise_()
        self._fade_in()


