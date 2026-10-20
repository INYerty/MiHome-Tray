# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct pointer tracking. Drag locally, commit only on release."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSlider, QStyle

from app.ui.si_theme import SiColors


class SmoothSlider(QSlider):
    committed = Signal()

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setFixedHeight(26)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 5px; background: {SiColors.LINE}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {SiColors.THEME}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {SiColors.TEXT_PRIMARY}; width: 16px; margin: -6px 0; border-radius: 8px; }}")

    def wheelEvent(self, event):
        event.ignore()

    def _pointer_value(self, event):
        span = max(1, self.width() - 16)
        pos = max(0, min(span, round(event.position().x()) - 8))
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, span,
                                              self.layoutDirection() == Qt.RightToLeft)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setSliderDown(True)
        self.setSliderPosition(self._pointer_value(event))
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.isSliderDown():
            return super().mouseMoveEvent(event)
        self.setSliderPosition(self._pointer_value(event))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self.isSliderDown():
            return super().mouseReleaseEvent(event)
        self.setSliderPosition(self._pointer_value(event))
        self.setSliderDown(False)
        self.committed.emit()
        event.accept()

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                           Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown) and not event.isAutoRepeat():
            self.committed.emit()
