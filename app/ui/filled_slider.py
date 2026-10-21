# SPDX-License-Identifier: GPL-3.0-or-later
"""Thick colored control rail with a small white position marker.

Only painting and pointer geometry differ from SmoothSlider: values follow the
pointer immediately, and a device write is committed only on release.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyleOptionSlider

from app.ui.smooth_slider import SmoothSlider


class FilledSlider(SmoothSlider):
    def __init__(self, orientation=Qt.Horizontal, parent=None, color="#ffbf00"):
        super().__init__(orientation, parent)
        self._color = QColor(color)
        self._segments: tuple[str, ...] = ()
        self._unknown = False
        if not self._color.isValid():
            raise ValueError("Invalid slider color")
        self.setFixedHeight(42)
        # The complete rail is custom painted. Native QSS handle dimensions must
        # not change the painted rail's pointer geometry.
        self.setStyleSheet("background: transparent; border: none;")
        self.valueChanged.connect(self.update)

    @property
    def segments(self) -> tuple[str, ...]:
        """Labels in logical device-value order, independent of RTL layout."""
        return self._segments

    def setSegments(self, labels: list[str]) -> None:  # noqa: N802
        """Use equal-width discrete choices; an empty list restores free motion.

        Discrete values are zero-based indexes into these labels. The host owns
        the mapping from indexes to actual device enumeration values. Clearing
        the labels leaves the range available for the host to set explicitly.
        """
        self._segments = tuple(str(label) for label in labels)
        if self._segments:
            self.setRange(0, len(self._segments) - 1)
            self.setSingleStep(1)
            self.setPageStep(1)
        self.update()

    def setColor(self, color) -> None:  # noqa: N802 (Qt API)
        value = QColor(color)
        if not value.isValid():
            raise ValueError("Invalid slider color")
        self._color = value
        self.update()

    def setUnknown(self, unknown: bool) -> None:  # noqa: N802
        """Hide the current-value indicator when the device has no valid value.

        Keep the numeric position untouched so displaying an unknown state does
        not emit a value change or accidentally submit a default device value.
        """
        self._unknown = bool(unknown)
        self.update()

    def isUnknown(self) -> bool:  # noqa: N802
        return self._unknown

    def _rail(self) -> QRectF:
        return QRectF(1, 1, max(1, self.width() - 2), max(1, self.height() - 2))

    def _option(self) -> QStyleOptionSlider:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return option

    def _pointer_value(self, event):
        if self.orientation() != Qt.Horizontal:
            return super()._pointer_value(event)
        rail = self._rail()
        if self._segments:
            fraction = max(0.0, min(1.0, (event.position().x() - rail.left()) / rail.width()))
            if self._option().upsideDown:
                fraction = 1.0 - fraction
            return min(len(self._segments) - 1, int(fraction * len(self._segments)))
        span = max(1, round(rail.width()))
        position = max(0, min(span, round(event.position().x() - rail.left())))
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), position, span, self._option().upsideDown)

    def paintEvent(self, event):  # noqa: N802
        if self.orientation() != Qt.Horizontal:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        rail = self._rail()
        path = QPainterPath()
        path.addRoundedRect(rail, 10, 10)
        # A dark tint makes the available portion legible on charcoal cards.
        tint = QColor(self._color)
        tint.setAlpha(42)
        painter.fillPath(path, tint)
        span = max(1, round(rail.width()))
        upside_down = self._option().upsideDown
        if self._segments:
            fraction = (self.sliderPosition() + 1) / len(self._segments)
            position = rail.width() * (1.0 - fraction if upside_down else fraction)
        else:
            position = QStyle.sliderPositionFromValue(
                self.minimum(), self.maximum(), self.sliderPosition(), span, upside_down)
        edge = rail.left() + position
        fill = (QRectF(edge, rail.top(), rail.right() - edge, rail.height())
                if upside_down else QRectF(rail.left(), rail.top(), position, rail.height()))
        painter.save()
        painter.setClipPath(path)
        painter.setBrush(self._color)
        if not self._unknown and fill.width() > 0:
            painter.drawRoundedRect(fill, 10, 10)
        painter.restore()
        if self._segments:
            self._paint_segments(painter, rail, upside_down)
        # The marker stays inside the rounded corners at the two endpoints;
        # the fill boundary itself always matches the pointer's mapped value.
        marker_x = max(rail.left() + 8, min(rail.right() - 8, edge + (8 if upside_down else -8)))
        if not self._unknown:
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(QRectF(marker_x - 2, rail.center().y() - 10, 4, 20), 2, 2)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor("#ffffff"))
            painter.drawRoundedRect(rail.adjusted(1, 1, -1, -1), 9, 9)

    def _paint_segments(self, painter: QPainter, rail: QRectF, upside_down: bool) -> None:
        count = len(self._segments)
        width = rail.width() / count
        painter.save()
        # Separators are drawn on both the fill and the remaining tinted rail.
        painter.setPen(QColor(255, 255, 255, 75))
        for index in range(1, count):
            x = rail.left() + index * width
            painter.drawLine(round(x), round(rail.top() + 6), round(x), round(rail.bottom() - 6))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        for index, label in enumerate(self._segments):
            physical = count - index - 1 if upside_down else index
            segment = QRectF(rail.left() + physical * width, rail.top(), width, rail.height())
            # Leave space for the marker at the selected segment's outer edge.
            text_rect = segment.adjusted(14 if upside_down else 6, 0,
                                         -6 if upside_down else -14, 0)
            painter.setPen(QColor("#1c1c1c") if not self._unknown and index <= self.sliderPosition()
                           else QColor("#dddddd"))
            text = painter.fontMetrics().elidedText(label, Qt.ElideRight, max(0, round(text_rect.width())))
            painter.drawText(text_rect, Qt.AlignCenter, text)
        painter.restore()

