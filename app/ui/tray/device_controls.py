# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact spec-driven light/fan controls for the tray flyout."""

from PySide6.QtCore import Qt, Signal, QSize
import qtawesome as qta
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
    QSizePolicy, QVBoxLayout,
)

from app.ui.si_theme import SiColors
from app.ui.glass import tint
from app.ui.smooth_slider import SmoothSlider


class NoWheelSlider(SmoothSlider):
    pass


class NoWheelCombo(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class QuickDeviceCard(QFrame):
    open_details = Signal(str)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self._did = session.device.did
        self._controls = {}
        self._signature = None
        self.setObjectName("quickDeviceCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setStyleSheet(
            f"QFrame#quickDeviceCard {{ background: {tint(SiColors.CARD, 125)}; border: 1px solid {tint(SiColors.TEXT_PRIMARY, 22)}; border-radius: 18px; }}"
            f"QLabel {{ color: {SiColors.TEXT_PRIMARY}; background: transparent; border: none; }}"
            f"QPushButton, QComboBox {{ color: {SiColors.TEXT_PRIMARY}; background: {tint(SiColors.SURFACE, 155)}; border: none; border-radius: 10px; padding: 5px 10px; }}"
            f"QPushButton:hover, QComboBox:hover {{ background: {SiColors.BTN_HOVER}; }}"
            f"QPushButton:checked {{ background: {SiColors.THEME}; color: {SiColors.ON_THEME_TEXT}; }}"
            "QPushButton#cardAction { background: transparent; padding: 0; border-radius: 12px; }"
            "QPushButton:disabled, QComboBox:disabled { color: #808080; }"
            f"QSlider::groove:horizontal {{ height: 5px; background: {SiColors.LINE}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {SiColors.THEME}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {SiColors.TEXT_PRIMARY}; width: 14px; margin: -5px 0; border-radius: 7px; }}")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(qta.icon('mdi.fan' if '.fan.' in session.device.model else 'mdi.desk-lamp', color=SiColors.THEME).pixmap(22, 22))
        header.addWidget(icon)
        self._name = QLabel(session.device.name)
        self._name.setWordWrap(True)
        self._name.setStyleSheet("font-weight: 600;")
        header.addWidget(self._name, 1)
        self._retry = QPushButton()
        self._retry.setObjectName("cardAction")
        self._retry.setFixedSize(26, 26)
        self._retry.setIcon(qta.icon('mdi.refresh', color=SiColors.TEXT_SECONDARY))
        self._retry.setToolTip("刷新状态")
        self._retry.setAccessibleName("刷新 " + session.device.name)
        self._retry.setAutoDefault(False)
        self._retry.clicked.connect(session.retry)
        header.addWidget(self._retry)
        details = QPushButton()
        details.setObjectName("cardAction")
        details.setFixedSize(26, 26)
        details.setIcon(qta.icon('mdi.chevron-right', color=SiColors.TEXT_SECONDARY))
        details.setAccessibleName("详情 " + session.device.name)
        details.setAutoDefault(False)
        details.setToolTip("打开设备的全部功能")
        details.clicked.connect(lambda: self.open_details.emit(self._did))
        header.addWidget(details)
        self._layout.addLayout(header)
        self._state = QLabel()
        self._state.setWordWrap(True)
        self._state.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; font-size: 8pt;")
        self._body = QVBoxLayout()
        self._body.setSpacing(10)
        self._layout.addLayout(self._body)
        self._layout.addWidget(self._state)
        session.changed.connect(self._render)
        self._render()

    def _build_controls(self):
        self._controls.clear()
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for prop in self.session.props:
            line = QFrame()
            row = QHBoxLayout(line) if prop.type == "bool" or prop.value_list else QVBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            label = QLabel(prop.desc)
            row.addWidget(label)
            if prop.type == "bool" or prop.value_list:
                row.addStretch(1)
            if prop.type == "bool":
                control = QPushButton("状态未知")
                control.setCheckable(True)
                control.setAutoDefault(False)
                control.setMinimumWidth(76)
                control.clicked.connect(lambda checked, p=prop: self.session.request_write(p.name, checked))
            elif prop.value_list:
                control = NoWheelCombo()
                for value in prop.value_list:
                    control.addItem(str(value.get("desc_zh_cn") or value.get("description") or value["value"]), value["value"])
                control.activated.connect(lambda index, p=prop, c=control: self.session.request_write(p.name, c.itemData(index)))
            else:
                lo, hi, step = prop.range
                step = step or 1
                control = NoWheelSlider(Qt.Horizontal)
                control.setRange(0, round((hi - lo) / step))

                def value_for(index, p=prop, low=lo, increment=step):
                    value = round(low + index * increment, 6)
                    return float(value) if p.type in ("float", "double") else int(value)

                def caption(index, p=prop, lbl=label, convert=value_for):
                    lbl.setText(f"{p.desc}  {convert(index):g}")

                control.valueChanged.connect(caption)
                control.sliderPressed.connect(lambda: setattr(self.session, "editing", True))
                def released(p=prop, c=control, convert=value_for):
                    self.session.editing = False
                    self.session.request_write(p.name, convert(c.value()))
                control.committed.connect(released)
            control.setAccessibleName(f"{self.session.device.name} {prop.desc}")
            if not isinstance(control, QSlider):
                control.setMinimumHeight(28)
            row.addWidget(control)
            self._body.addWidget(line)
            self._controls[prop.name] = (prop, control, label)

    def _render(self):
        state = self.session
        signature = tuple(p.name for p in state.props)
        if signature != self._signature:
            self._signature = signature
            self._build_controls()
        self._name.setText(state.device.name)
        stamp = state.updated_at.strftime("%H:%M:%S") if state.updated_at else "尚无读数"
        self._state.setText(f"{state.device.room_name} · {state.message} · {stamp}")
        self._state.setStyleSheet(f"color: {SiColors.ERROR_TEXT if state.error else SiColors.TEXT_SECONDARY}; font-size: 8pt;")
        self._state.setToolTip(state.message)
        self._retry.setEnabled(not state.busy and not state._inflight)
        for name, (prop, control, label) in self._controls.items():
            value = state.values.get(name)
            if isinstance(control, QSlider) and control.isSliderDown():
                continue
            slider = isinstance(control, QSlider)
            control.setEnabled(state.device.online and state.presence_known and value is not None
                               and (slider or not state.busy and not state._inflight))
            if slider and state.requested and state.requested[0] == name:
                value = state.requested[1]  # keep the released thumb still while cloud confirmation is pending
            control.blockSignals(True)
            if prop.type == "bool":
                control.setChecked(bool(value) if value is not None else False)
                control.setText("已开启" if value else "已关闭" if value is not None else "状态未知")
            elif prop.value_list:
                control.setCurrentIndex(control.findData(value) if value is not None else -1)
            elif value is not None:
                lo, hi, step = prop.range
                control.setValue(round((value - lo) / (step or 1)))
                label.setText(f"{prop.desc}  {value:g}")
            else:
                label.setText(f"{prop.desc} · 状态未知")
            control.blockSignals(False)
