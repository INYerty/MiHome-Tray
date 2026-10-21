# SPDX-License-Identifier: GPL-3.0-or-later
# MiHome-Windows: 米家设备的 Windows 桌面控制端
# Copyright (C) 2026 MiHome-Windows contributors
"""托盘管理对话框用的拖拽排序行。"""

import shiboken6

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame


TRAY_ORDER_MIME = "application/x-mihome-tray-item"


class _DraggableRow(QFrame):
    """支持拖拽排序的行。"""

    dragStarted = Signal(str)  # noqa: N815
    dragFinished = Signal()  # noqa: N815

    def __init__(self, did: str, parent=None):
        super().__init__(parent)
        self._did = did
        self._dragging = False
        self._drag_start = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag_start = e.pos()
            self._dragging = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_start is None or not e.buttons() & Qt.LeftButton:
            return
        if not self._dragging:
            dist = (e.pos() - self._drag_start).manhattanLength()
            if dist >= QApplication.startDragDistance():
                self._dragging = True
                self.dragStarted.emit(self._did)
                # 先抓图再隐藏：用透明度保持占位，避免布局收缩
                pixmap = self.grab()
                from PySide6.QtWidgets import QGraphicsOpacityEffect
                eff = QGraphicsOpacityEffect(self)
                eff.setOpacity(0.25)
                self.setGraphicsEffect(eff)
                from PySide6.QtGui import QDrag
                drag = QDrag(self)
                from PySide6.QtCore import QMimeData
                mime = QMimeData()
                mime.setData(TRAY_ORDER_MIME, self._did.encode("utf-8"))
                mime.setText(self._did)
                drag.setMimeData(mime)
                drag.setPixmap(pixmap)
                drag.setHotSpot(self._drag_start)
                self.setCursor(Qt.ClosedHandCursor)
                try:
                    drag.exec(Qt.MoveAction)
                finally:
                    if shiboken6.isValid(self):
                        self.setGraphicsEffect(None)
                        self._dragging = False
                        self._drag_start = None
                        self.setCursor(Qt.OpenHandCursor)
                        self.dragFinished.emit()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._dragging = False
        self._drag_start = None
        super().mouseReleaseEvent(e)


