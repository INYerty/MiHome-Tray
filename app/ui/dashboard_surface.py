# SPDX-License-Identifier: GPL-3.0-or-later
"""Subtle dashboard ambience; painting pauses while hidden or disabled."""
import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.core import settings_store
from app.ui.si_theme import SiColors, is_dark


class DashboardSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._advance)
        self._enabled = settings_store.get_ambient_enabled()

    def sync_effects(self):
        self._enabled = settings_store.get_ambient_enabled()
        self._timer.setInterval(100)
        if self._enabled and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance(self):
        self._phase = (self._phase + 0.008) % math.tau
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_effects()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(SiColors.WINDOW_BG))
        painter.drawRoundedRect(self.rect(), 20, 20)
        if not self._enabled:
            return
        painter.setClipRect(self.rect().adjusted(2, 2, -2, -2))
        w, h = self.width(), self.height()
        for x, y, radius, color in (
            (w * (0.12 + 0.04 * math.sin(self._phase)), h * 0.05, w * 0.62, SiColors.THEME),
            (w * 0.95, h * (0.8 + 0.08 * math.cos(self._phase)), w * 0.48, "#ffbf00"),
        ):
            tint = QColor(color)
            tint.setAlpha(10 if is_dark() else 8)
            gradient = QRadialGradient(QPointF(x, y), max(1.0, radius))
            gradient.setColorAt(0, tint)
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(gradient)
            painter.drawRect(self.rect())
