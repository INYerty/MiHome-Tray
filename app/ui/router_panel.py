# SPDX-License-Identifier: GPL-3.0-or-later
"""Router telemetry shared by the home detail drawer and tray subpanel."""

from collections import deque
import time
import shiboken6

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from app.core.router import RouterSnapshot, property_text, rate_text, rate_value
from app.ui.si_theme import SiColors


class _RateGraph(QWidget):
    def __init__(self, prop, parent=None):
        super().__init__(parent)
        self.prop = prop
        self.samples = deque(maxlen=60)
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def append(self, timestamp, value):
        self.samples.append((timestamp, rate_value(value)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 24, -10, -16)
        color = QColor(SiColors.THEME if self.prop.name == "download-speed" else SiColors.TEXT_SUBTLE)
        values = [v for _, v in self.samples if v is not None]
        peak = max(values, default=0) or 1
        painter.setPen(QColor(SiColors.TEXT_SECONDARY))
        latest = self.samples[-1][1] if self.samples else None
        painter.drawText(10, 16, f"{self.prop.label}  {rate_text(self.prop, latest)}")
        painter.setPen(QPen(QColor(SiColors.LINE), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if len(self.samples) < 2:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "等待更多采样…")
            return
        last_time = self.samples[-1][0]
        first_time = max(self.samples[0][0], last_time - 300)
        duration = max(last_time - first_time, 1)
        path = QPainterPath()
        connected = False
        previous_time = None
        for timestamp, value in self.samples:
            if value is None or timestamp < first_time:
                connected = False
                continue
            point = QPointF(rect.left() + (timestamp - first_time) / duration * rect.width(),
                            rect.bottom() - value / peak * rect.height())
            # Reopening a hidden panel leaves a real time gap, not an invented line.
            if not connected or (previous_time is not None and timestamp - previous_time > 15):
                path.moveTo(point)
            else:
                path.lineTo(point)
            connected, previous_time = True, timestamp
        painter.setPen(QPen(color, 2))
        painter.drawPath(path)
        painter.setPen(QColor(SiColors.TEXT_MUTED))
        painter.drawText(10, self.height() - 1, f"最近 {duration:.0f} 秒 · 独立刻度 0—{peak:g}")


class RouterPanel(QFrame):
    """Refresh every five seconds while visible, with at most one pending job."""

    def __init__(self, service, jobs, device, parent=None):
        super().__init__(parent)
        self._service, self._jobs, self.device = service, jobs, device
        self._busy = False
        self._graphs = {}
        self._fields = {}
        self._signature = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)
        header = QHBoxLayout()
        self._title = QLabel(f"{device.name} · 网络状态", self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)
        header.addWidget(self._title, 1)
        self._refresh = QPushButton("刷新", self)
        self._refresh.setAutoDefault(False)
        self._refresh.clicked.connect(self.refresh)
        header.addWidget(self._refresh)
        self._layout.addLayout(header)
        self._status = QLabel("读取账号设备提供的网络状态…", self)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        self._layout.addWidget(self._status)
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(6)
        self._layout.addWidget(self._body)
        self._note = QLabel(self)
        self._note.setWordWrap(True)
        self._layout.addWidget(self._note)
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self.retheme()

    def retheme(self):
        self.setStyleSheet(f"RouterPanel {{background:{SiColors.CARD};border:1px solid {SiColors.LINE};border-radius:14px;}}")
        self._title.setStyleSheet(f"color:{SiColors.TEXT_PRIMARY};font-size:14px;font-weight:600;")
        for label in (self._status, self._note, *self._fields.values()):
            label.setStyleSheet(f"color:{SiColors.TEXT_SECONDARY};font-size:12px;")
        for graph in self._graphs.values():
            graph.update()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self):
        if self._busy or not self.isVisible():
            return
        if not self.device.online:
            self._status.setText("设备离线，恢复在线后可重新打开查看。")
            self._timer.stop()
            return
        self._busy = True
        self._refresh.setEnabled(False)
        self._jobs.submit(lambda: self._service.router_snapshot(self.device.did),
                          on_success=self._loaded, on_error=self._failed)

    def _rebuild(self, capabilities):
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._graphs.clear()
        self._fields.clear()
        for prop in capabilities.rates:
            graph = _RateGraph(prop, self._body)
            self._graphs[prop.key] = graph
            self._body_layout.addWidget(graph)
        if not capabilities.rates:
            label = QLabel("此型号未公开实时网速属性。", self._body)
            label.setWordWrap(True)
            self._body_layout.addWidget(label)
        for prop in capabilities.attributes + capabilities.client_fields:
            label = QLabel(self._body)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._fields[prop.key] = label
            self._body_layout.addWidget(label)
        self.retheme()

    def _loaded(self, snapshot: RouterSnapshot):
        if not shiboken6.isValid(self):
            return
        self._busy = False
        self._refresh.setEnabled(True)
        capabilities = snapshot.capabilities
        if capabilities != self._signature:
            self._signature = capabilities
            self._rebuild(capabilities)
        for prop in capabilities.rates:
            self._graphs[prop.key].append(snapshot.timestamp, snapshot.values.get(prop.key))
        for prop in capabilities.attributes + capabilities.client_fields:
            self._fields[prop.key].setText(f"{prop.label}：{property_text(prop, snapshot.values.get(prop.key))}")
        available = sum(value is not None for value in snapshot.values.values())
        self._status.setText(f"{time.strftime('%H:%M:%S')} 更新 · 可见时每 5 秒采样"
                             if available else "设备未返回可用网络数据。")
        notes = []
        if any(not prop.unit for prop in capabilities.rates):
            notes.append("部分网速未声明单位，图表保留设备原始值。")
        if not capabilities.client_fields:
            notes.append("此型号的账号接口未公开连接设备明细；如有连接数量，会显示在上方。")
        else:
            notes.append("连接设备字段按型号原样展示；接口未提供关联关系时不合并为设备列表。")
        self._note.setText("\n".join(notes))
        if not capabilities.properties:
            self._timer.stop()

    def _failed(self, error):
        if not shiboken6.isValid(self):
            return
        self._busy = False
        self._refresh.setEnabled(True)
        self._status.setText(f"读取失败：{error}\n图表保留此前读数，可点击刷新重试。")
        now = time.monotonic()
        for graph in self._graphs.values():
            graph.append(now, None)
