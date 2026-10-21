# SPDX-License-Identifier: GPL-3.0-or-later
"""Pointer geometry is independent of native slider/stylesheet handle sizes."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.filled_slider import FilledSlider


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_filled_slider_uses_full_rail_and_only_commits_on_release(qapp):
    slider = FilledSlider(Qt.Horizontal, color="#ffbf00")
    slider.setRange(0, 100)
    slider.resize(340, 42)
    slider.show()
    qapp.processEvents()
    commits = []
    slider.committed.connect(lambda: commits.append(slider.value()))
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(1, 21))
    assert slider.value() == 0
    QTest.mouseMove(slider, QPoint(170, 21))
    assert slider.value() == 50 and commits == []
    QTest.mouseMove(slider, QPoint(339, 21))
    assert slider.value() == 100 and commits == []
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(339, 21))
    assert commits == [100]
    slider.close()


@pytest.mark.parametrize("rtl,inverted", [(True, False), (False, True)])
def test_filled_slider_reversed_endpoints(qapp, rtl, inverted):
    slider = FilledSlider(Qt.Horizontal, color="#39b9e6")
    slider.resize(340, 42)
    slider.setRange(10, 90)
    slider.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    slider.setInvertedAppearance(inverted)
    slider.show()
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(1, 21))
    assert slider.value() == 90
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(339, 21))
    assert slider.value() == 10
    slider.close()


@pytest.mark.parametrize("rtl,inverted", [(False, False), (True, False), (False, True), (True, True)])
def test_segmented_slider_selects_every_segment_and_endpoints(qapp, rtl, inverted):
    slider = FilledSlider(color="#39b9e6")
    slider.resize(340, 42)
    labels = ["低", "中", "高"]
    slider.setSegments(labels)
    labels[0] = "不影响已设置标签"
    assert slider.segments == ("低", "中", "高")
    assert (slider.minimum(), slider.maximum()) == (0, 2)
    slider.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    slider.setInvertedAppearance(inverted)
    slider.show()
    reverse = rtl != inverted
    for physical_index, x in enumerate([56, 170, 283]):
        QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(x, 21))
        assert slider.value() == (2 - physical_index if reverse else physical_index)
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(0, 21))
    assert slider.value() == (2 if reverse else 0)
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(340, 21))
    assert slider.value() == (0 if reverse else 2)
    slider.close()


def test_segmented_slider_commits_only_final_index_and_keyboard_steps(qapp):
    slider = FilledSlider()
    slider.resize(340, 42)
    slider.setSegments(["低", "中", "高"])
    slider.show()
    commits = []
    slider.committed.connect(lambda: commits.append(slider.value()))
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(30, 21))
    QTest.mouseMove(slider, QPoint(200, 21))
    assert slider.value() == 1 and commits == []
    QTest.mouseMove(slider, QPoint(320, 21))
    assert slider.value() == 2 and commits == []
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(320, 21))
    assert commits == [2]
    QTest.keyClick(slider, Qt.Key_Left)
    assert slider.value() == 1 and commits == [2, 1]
    slider.close()


def test_first_segment_has_visible_fill_and_empty_labels_restore_continuous(qapp):
    slider = FilledSlider(color="#ffbf00")
    slider.resize(340, 42)
    slider.setSegments(["低", "中", "高"])
    slider.setValue(0)
    slider.show()
    qapp.processEvents()
    image = slider.grab().toImage()
    assert image.pixelColor(40, 5).name() == "#ffbf00"
    assert image.pixelColor(200, 5).name() != "#ffbf00"
    slider.setSegments([])
    slider.setRange(0, 100)
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(170, 21))
    assert slider.segments == () and slider.value() == 50
    slider.close()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("segmented", [True, False])
def test_unknown_has_no_fill_or_marker_and_does_not_change_value(qapp, enabled, segmented):
    slider = FilledSlider(color="#ffbf00")
    slider.resize(340, 42)
    if segmented:
        slider.setSegments(["低", "中", "高"])
        slider.setValue(0)
        marker_x = 105
    else:
        slider.setRange(0, 100)
        slider.setValue(50)
        marker_x = 162
    slider.setEnabled(enabled)
    slider.show()
    slider.clearFocus()
    qapp.processEvents()
    known = slider.grab().toImage()
    assert known.pixelColor(40, 5) != known.pixelColor(200, 5)
    assert known.pixelColor(marker_x, 14) != known.pixelColor(marker_x - 10, 14)
    changes, commits = [], []
    slider.valueChanged.connect(changes.append)
    slider.committed.connect(lambda: commits.append(slider.value()))
    slider.setUnknown(True)
    unknown = slider.grab().toImage()
    # First-segment fill and white marker both disappear, including disabled UI.
    assert unknown.pixelColor(40, 5) == unknown.pixelColor(200, 5)
    assert unknown.pixelColor(marker_x, 14) == unknown.pixelColor(marker_x - 10, 14)
    assert slider.isUnknown() and slider.value() == (0 if segmented else 50)
    assert changes == [] and commits == []
    slider.setUnknown(False)
    restored = slider.grab().toImage()
    assert not slider.isUnknown()
    assert restored.pixelColor(40, 5) == known.pixelColor(40, 5)
    slider.close()
