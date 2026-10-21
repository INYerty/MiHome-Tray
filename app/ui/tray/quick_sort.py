# SPDX-License-Identifier: GPL-3.0-or-later
"""Handle-only ordering for quick popup cards, retaining the caller's grid layout."""

import shiboken6

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from app.ui.si_theme import SiColors


QUICK_SORT_MIME = "application/x-mihome-quick-card"


class _SortHandle(QToolButton):
    drag_finished = Signal()

    def __init__(self, key: str, card: QWidget, parent=None):
        super().__init__(parent)
        self.key = key
        self.card = card
        self._press = None
        self.setText("⠿")
        self.setFixedSize(34, 24)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动此手柄调整顺序")
        self.setStyleSheet(f"QToolButton {{ color: {SiColors.TEXT_SECONDARY}; background: transparent; border: none; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or not event.buttons() & Qt.LeftButton:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        origin = self.mapTo(self.card, self._press)
        self._press = None
        self.setDown(False)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(QUICK_SORT_MIME, self.key.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.card.grab())
        drag.setHotSpot(origin)
        self.setCursor(Qt.ClosedHandCursor)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            if shiboken6.isValid(self):
                self.setCursor(Qt.OpenHandCursor)
                self.drag_finished.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None
        super().mouseReleaseEvent(event)


class QuickSortController(QObject):
    """Wrap cards before adding them to an existing grid.

    ``order_changed`` emits the full key sequence, without saving or rebuilding.
    Call ``clear`` before rebuilding, then ``wrap_card`` in the current order.
    The viewport argument can be a QScrollArea viewport; edge dragging scrolls it.
    """

    order_changed = Signal(list)

    def __init__(self, container: QWidget, viewport: QWidget | None = None, parent=None):
        super().__init__(parent or container)
        self._container = container
        self._viewport = viewport or container
        self._cards: dict[str, QWidget] = {}
        self._handles: dict[str, _SortHandle] = {}
        self._bars: list[QWidget] = []
        self._enabled = False
        for widget in {container, self._viewport}:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)
        self._line = QFrame(container)
        self._line.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._line.setStyleSheet(f"background: {SiColors.THEME}; border-radius: 2px;")
        self._line.hide()

    def wrap_card(self, key: str, content: QWidget) -> QWidget:
        wrapper = QFrame(self._container)
        wrapper.setObjectName("quickSortableCard")
        wrapper.setStyleSheet("QFrame#quickSortableCard { background: transparent; border: none; }")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        bar = QWidget(wrapper)
        row = QHBoxLayout(bar)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)
        handle = _SortHandle(key, wrapper, bar)
        handle.drag_finished.connect(self._line.hide)
        row.addWidget(handle)
        hint = QLabel("拖动排序", bar)
        hint.setStyleSheet(f"color: {SiColors.TEXT_MUTED}; background: transparent; font-size: 8pt;")
        row.addWidget(hint)
        row.addStretch(1)
        layout.addWidget(bar)
        layout.addWidget(content)
        bar.setVisible(self._enabled)
        self._cards[key] = wrapper
        self._handles[key] = handle
        self._bars.append(bar)
        return wrapper

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._line.hide()
        for bar in self._bars:
            bar.setVisible(enabled)

    def clear(self) -> None:
        self._line.hide()
        self._cards.clear()
        self._handles.clear()
        self._bars.clear()

    def _hit_insert(self, pos, source_key: str) -> tuple[str | None, bool]:
        source = self._cards.get(source_key)
        if source is not None and source.geometry().contains(pos):
            return source_key, False
        candidates = [(key, card.geometry()) for key, card in self._cards.items()
                      if key != source_key]
        if not candidates:
            return source_key, False
        if pos.y() > max(rect.bottom() for _, rect in candidates):
            return None, True
        def distance(item):
            rect = item[1]
            dx = max(rect.left() - pos.x(), 0, pos.x() - rect.right())
            dy = max(rect.top() - pos.y(), 0, pos.y() - rect.bottom())
            return dx * dx + dy * dy
        key, rect = min(candidates, key=distance)
        if self._is_grid():
            return key, pos.x() >= rect.center().x()
        return key, pos.y() >= rect.center().y()

    def _is_grid(self) -> bool:
        return len({card.x() for card in self._cards.values()}) > 1

    def _ordered_drop(self, source: str, pos) -> list[str]:
        order = list(self._cards)
        target, after = self._hit_insert(pos, source)
        if target == source:
            return order
        order.remove(source)
        index = len(order) if target is None else order.index(target) + int(after)
        order.insert(index, source)
        return order

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() not in (QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop):
            return super().eventFilter(obj, event)
        if event.type() == QEvent.DragLeave:
            self._line.hide()
            event.accept()
            return True
        mime = event.mimeData()
        key = (bytes(mime.data(QUICK_SORT_MIME)).decode("utf-8", errors="replace")
               if mime.hasFormat(QUICK_SORT_MIME) else None)
        if not self._enabled or key not in self._cards or event.source() is not self._handles[key]:
            self._line.hide()
            event.ignore()
            return True
        point = event.position().toPoint()
        viewport_pos = self._viewport.mapFrom(obj, point)
        if not self._viewport.rect().contains(viewport_pos):
            self._line.hide()
            event.ignore()
            return True
        pos = self._container.mapFrom(obj, point)
        if event.type() == QEvent.Drop:
            self._line.hide()
            order = self._ordered_drop(key, pos)
            event.acceptProposedAction()
            if order != list(self._cards):
                self.order_changed.emit(order)
            return True
        target, after = self._hit_insert(pos, key)
        if target == key:
            self._line.hide()
        else:
            rect = self._cards[target or list(self._cards)[-1]].geometry()
            if self._is_grid() and target is not None:
                x = rect.right() + 3 if after else max(0, rect.left() - 4)
                self._line.setGeometry(x, rect.top(), 3, rect.height())
            else:
                y = rect.bottom() + 3 if after else max(0, rect.top() - 4)
                self._line.setGeometry(rect.left(), y, rect.width(), 3)
            self._line.show()
            self._line.raise_()
        area = self._viewport.parentWidget()
        if hasattr(area, "verticalScrollBar"):
            bar = area.verticalScrollBar()
            if viewport_pos.y() < 28:
                bar.setValue(bar.value() - 12)
            elif viewport_pos.y() > self._viewport.height() - 28:
                bar.setValue(bar.value() + 12)
        event.acceptProposedAction()
        return True
