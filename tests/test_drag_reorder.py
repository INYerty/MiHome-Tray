# SPDX-License-Identifier: GPL-3.0-or-later
"""Drag geometry regressions; simulated cards and storage, no account access."""

from time import monotonic
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QWidget

from app.ui.workbench_item import WORKBENCH_MIME, WorkbenchItemWrapper
from app.ui.workbench_panel import WorkbenchPanel
from app.ui.tray.quick_sort import QuickSortController
from app.ui.tray.manager_dialog import TrayManagerDialog
from app.core.models import DeviceInfo


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def wait_for_reorder(panel, qapp, timeout=2.0):
    # Qt's unified animation timer can deliver its first frame late under load.
    # A nominal-duration sleep is not evidence that the animation has finished.
    deadline = monotonic() + timeout
    while panel._reordering and monotonic() < deadline:
        QTest.qWait(10)
    assert not panel._reordering, "reorder animation did not complete"
    assert panel._reorder_group is None
    qapp.processEvents()  # Consume the layout request posted when layout re-enables.


@pytest.fixture
def panel(qapp, monkeypatch):
    monkeypatch.setattr("app.ui.workbench_panel.workbench_store.save", lambda *args: None)
    widget = WorkbenchPanel(None, None)
    widget._current_did = "simulated"
    widget._reload_readings = lambda: None
    widget._active_keys = list("abcd")
    widget._module_builders = {key: QFrame for key in widget._active_keys}
    widget.resize(800, 580)
    widget._render_workbench()
    widget._set_mode("manage")
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget._clear_grid()
    widget.deleteLater()
    qapp.processEvents()


def test_workbench_drop_on_itself_keeps_order(panel):
    panel._apply_drop("a", panel._wrappers["a"].geometry().center())
    assert panel._active_keys == list("abcd")


def test_workbench_lower_half_inserts_after_and_gap_is_not_end(panel, qapp):
    target = panel._wrappers["b"].geometry()
    gap = QPoint(target.center().x(), target.bottom() + 3)
    assert panel._hit_insert(gap, "a") == ("b", True)
    panel._apply_drop("a", QPoint(target.center().x(), target.bottom() - 2))
    assert panel._active_keys == list("bacd")
    wait_for_reorder(panel, qapp)


def test_workbench_narrow_popup_uses_one_column_and_resizes_back(panel, qapp):
    panel.resize(420, 580)
    qapp.processEvents()
    qapp.processEvents()
    assert panel._column_count == 1
    assert len({wrapper.x() for wrapper in panel._wrappers.values()}) == 1
    panel.resize(800, 580)
    qapp.processEvents()
    qapp.processEvents()
    assert panel._column_count == 2
    assert len({wrapper.x() for wrapper in panel._wrappers.values()}) == 2


def test_repeated_move_during_animation_preserves_final_layout(panel, qapp):
    panel._on_move("a", 1)
    panel._on_move("a", 1)
    wait_for_reorder(panel, qapp)
    assert panel._active_keys == list("bcad")
    # Replaying the current order must produce the same physical geometry.
    actual = {key: wrapper.geometry() for key, wrapper in panel._wrappers.items()}
    panel._reorder_with_animation({})
    wait_for_reorder(panel, qapp)
    assert {key: wrapper.geometry() for key, wrapper in panel._wrappers.items()} == actual


def test_workbench_drop_coordinates_include_scroll_offset(panel, qapp):
    panel.resize(420, 300)
    qapp.processEvents()
    qapp.processEvents()
    panel._body.verticalScrollBar().setValue(100)
    viewport = panel._body.viewport()
    point = QPoint(25, 70)
    received = []
    panel._apply_drop = lambda key, pos: received.append((key, pos))
    mime = QMimeData()
    mime.setData(WORKBENCH_MIME, b"a")
    event = SimpleNamespace(type=lambda: QEvent.Drop, mimeData=lambda: mime,
                            source=lambda: panel._wrappers["a"], position=lambda: QPointF(point),
                            ignore=lambda: None, acceptProposedAction=lambda: None)
    panel._handle_drag_event(viewport, event)
    assert received == [("a", panel._container.mapFrom(viewport, point))]
    assert received[0][1].y() > point.y()


def test_handle_filters_small_gesture_and_does_not_drag_inner_controls(qapp):
    wrapper = WorkbenchItemWrapper("demo", QFrame())
    wrapper.set_mode("manage")
    wrapper.resize(400, 116)
    wrapper.show()
    qapp.processEvents()
    starts = []
    wrapper._start_drag = lambda: starts.append(True)
    handle = wrapper._handle
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(8, 8), QPointF(8, 8),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(handle, press)
    tiny = QMouseEvent(QEvent.MouseMove, QPointF(9, 8), QPointF(9, 8),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(handle, tiny)
    assert not starts
    move = QMouseEvent(QEvent.MouseMove, QPointF(50, 8), QPointF(50, 8),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(handle, move)
    assert starts == [True]
    wrapper.close()
    wrapper.deleteLater()


def test_quick_grid_horizontal_half_and_blank_gap(qapp):
    host = QWidget()
    host.resize(500, 400)
    grid = QGridLayout(host)
    grid.setSpacing(12)
    controller = QuickSortController(host)
    for index, key in enumerate("abcd"):
        card = QFrame()
        card.setMinimumSize(180, 100)
        grid.addWidget(controller.wrap_card(key, card), index // 2, index % 2)
    host.show()
    qapp.processEvents()
    b = controller._cards["b"].geometry()
    assert controller._ordered_drop("a", QPoint(b.left() + 3, b.center().y())) == list("abcd")
    assert controller._ordered_drop("a", QPoint(b.right() - 3, b.center().y())) == list("bacd")
    assert controller._ordered_drop("a", controller._cards["a"].geometry().center()) == list("abcd")
    assert controller._hit_insert(QPoint(b.center().x(), b.bottom() + 2), "a")[0] == "b"
    host.close()
    host.deleteLater()


def test_tray_sort_uses_current_layout_and_half_row_positions(qapp, monkeypatch):
    monkeypatch.setattr("app.ui.tray.manager_dialog.tray_store.load", lambda: list("abcd"))
    monkeypatch.setattr("app.ui.tray.manager_dialog.tray_store.load_scenes", lambda: [])
    monkeypatch.setattr("app.ui.tray.manager_dialog.tray_store.load_order",
                        lambda: [{"type": "device", "id": key} for key in "abcd"])
    devices = [DeviceInfo(key, key, "test", "家", "房间", True) for key in "abcd"]
    dialog = TrayManagerDialog(devices)
    dialog._toggle_sort_view()
    dialog.show()
    qapp.processEvents()
    b = dialog._sort_rows["b"].geometry()
    dialog._apply_drop("a", QPoint(b.center().x(), b.bottom() - 1))
    qapp.processEvents()
    assert dialog._sort_layout_ids() == list("bacd")
    c = dialog._sort_rows["c"].geometry()
    dialog._apply_drop("b", QPoint(c.center().x(), c.bottom() - 1))
    assert dialog._sort_layout_ids() == list("acbd")
    assert [item["id"] for item in dialog.selected_order()] == list("acbd")
    dialog.close()
    dialog.deleteLater()
