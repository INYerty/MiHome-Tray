# SPDX-License-Identifier: GPL-3.0-or-later
"""One frame per device with individually selectable controls, no collapsed panel."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSlider,
    QSizePolicy, QVBoxLayout,
)
import qtawesome as qta
from app.core import settings_store
from app.core.control_scale import ControlScale
from app.ui.filled_slider import FilledSlider
from app.ui.glass import tint
from app.ui.power_button import PowerButton
from app.ui.si_theme import SiColors

_FAN_SPEEDS = {"fan-level", "speed-level", "wind-speed", "speed"}


def _semantic(prop):
    return prop.semantic_name or prop.name.replace("_", "-")


def _title(prop):
    return "色温" if _semantic(prop) == "color-temperature" else prop.desc


class NoWheelSlider(FilledSlider):
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
        self._controls, self._lines, self._scales = {}, {}, {}
        self._signature = None
        self._primary_name = self._power_name = None
        self._editing_control = None
        self._accent = "#ffbf00" if ".light." in session.device.model or ":light:" in session.device.spec_type else "#25b8b0"
        self.setObjectName("quickDeviceCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setStyleSheet(
            f"QFrame#quickDeviceCard {{ background: {SiColors.CARD}; border: 1px solid {SiColors.LINE}; border-radius: 12px; }}"
            f"QLabel {{ color: {SiColors.TEXT_PRIMARY}; background: transparent; border: none; }}"
            f"QPushButton, QComboBox {{ color: {SiColors.TEXT_PRIMARY}; background: {SiColors.SURFACE}; border: none; border-radius: 8px; padding: 4px 8px; }}"
            f"QPushButton:hover, QComboBox:hover {{ background: {SiColors.BTN_HOVER}; }}"
            f"QPushButton:checked {{ background: {SiColors.THEME}; color: {SiColors.ON_THEME_TEXT}; }}"
            "QPushButton#cardAction { background: transparent; padding: 0; border-radius: 12px; }"
            "QPushButton#cardAction::menu-indicator { image: none; width: 0; }"
            "QPushButton#powerBtn { padding: 0; }")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(6)
        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"background: {tint(self._accent, 48)}; border-radius: 18px;")
        is_switch = ".switch." in session.device.model or ":switch:" in session.device.spec_type
        symbol = "mdi.lightbulb" if self._accent == "#ffbf00" else "mdi.toggle-switch" if is_switch else "mdi.fan"
        icon.setPixmap(qta.icon(symbol, color=self._accent).pixmap(23, 23))
        header.addWidget(icon)
        title = QVBoxLayout()
        title.setSpacing(1)
        self._name = QLabel(session.device.name)
        self._name.setWordWrap(True)
        self._name.setStyleSheet("font-size: 10pt; font-weight: 600;")
        title.addWidget(self._name)
        self._summary = QLabel("读取中")
        self._summary.setStyleSheet("font-size: 8pt;")
        title.addWidget(self._summary)
        header.addLayout(title, 1)
        self._more = QPushButton()
        self._more.setObjectName("cardAction")
        self._more.setFixedSize(24, 24)
        self._more.setAutoDefault(False)
        self._more.setIcon(qta.icon('mdi.tune-variant', color=SiColors.TEXT_SECONDARY))
        self._more.setToolTip("选择这张设备卡片显示哪些控件")
        self._more.setAccessibleName("设置 " + session.device.name + " 的显示控件")
        self._control_menu = QMenu(self)
        self._control_menu.setObjectName("appMenu")
        self._control_menu.aboutToShow.connect(self._populate_visibility_menu)
        self._more.setMenu(self._control_menu)
        header.addWidget(self._more)
        self._retry = QPushButton()
        self._retry.setObjectName("cardAction")
        self._retry.setFixedSize(24, 24)
        self._retry.setAutoDefault(False)
        self._retry.setIcon(qta.icon('mdi.refresh', color=SiColors.TEXT_SECONDARY))
        self._retry.setToolTip("刷新状态")
        self._retry.clicked.connect(session.retry)
        header.addWidget(self._retry)
        details = QPushButton()
        details.setObjectName("cardAction")
        details.setFixedSize(24, 24)
        details.setAutoDefault(False)
        details.setIcon(qta.icon('mdi.chevron-right', color=SiColors.TEXT_SECONDARY))
        details.setToolTip("设备全部功能")
        details.clicked.connect(lambda: self.open_details.emit(self._did))
        header.addWidget(details)
        self._power = PowerButton(30, icon_size=20)
        self._power.setAutoDefault(False)
        self._power.setCheckable(True)
        self._power.setToolTip("设备开关")
        self._power.clicked.connect(self._toggle_power)
        self._power.hide()
        header.addWidget(self._power)
        self._layout.addLayout(header)
        self._body = QVBoxLayout()
        self._body.setSpacing(10)
        self._layout.addLayout(self._body)
        self._state = QLabel()
        self._state.setWordWrap(True)
        self._layout.addWidget(self._state)
        session.changed.connect(self._render)
        self._render()

    def _toggle_power(self, checked):
        if self._power_name is not None:
            self.session.request_write(self._power_name, checked)

    def _populate_visibility_menu(self):
        self._control_menu.clear()
        hidden = settings_store.get_tray_hidden_controls(self._did)
        if not self._controls:
            self._control_menu.addAction("暂未读取到常用功能").setEnabled(False)
            return
        for name, (prop, _, _) in self._controls.items():
            action = self._control_menu.addAction(_title(prop))
            action.setCheckable(True)
            action.setChecked(name not in hidden)
            action.toggled.connect(lambda checked, key=name: self.set_control_visible(key, checked))
        self._control_menu.addSeparator()
        self._control_menu.addAction("显示全部控件").triggered.connect(self._show_all)

    def _show_all(self):
        settings_store.set_tray_hidden_controls(self._did, [])
        self._apply_visibility()

    def set_control_visible(self, name: str, visible: bool):
        if name not in self._controls:
            return
        hidden = settings_store.get_tray_hidden_controls(self._did)
        hidden.discard(name) if visible else hidden.add(name)
        settings_store.set_tray_hidden_controls(self._did, hidden)
        if not visible and self._editing_control is self._controls[name][1]:
            self._end_edit()
        self._apply_visibility()

    def _apply_visibility(self):
        hidden = settings_store.get_tray_hidden_controls(self._did)
        self._power.setVisible(self._power_name is not None and self._power_name not in hidden)
        for name, line in self._lines.items():
            line.setVisible(name not in hidden)

    def _build_controls(self):
        self._end_edit()
        self._controls.clear()
        self._scales.clear()
        self._lines.clear()
        self._power_name = self._primary_name = None
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for prop in self.session.props:
            semantic = _semantic(prop)
            if semantic == "on" and prop.type == "bool" and self._power_name is None:
                self._power_name = prop.name
                self._controls[prop.name] = (prop, self._power, self._summary)
                continue
            fan_speed = semantic in _FAN_SPEEDS
            scale = ControlScale.from_prop(prop, segmented=fan_speed)
            line = QFrame()
            row = QHBoxLayout(line) if prop.type == "bool" or prop.value_list and not fan_speed else QVBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            label = QLabel(_title(prop))
            label.setWordWrap(True)
            label.setStyleSheet("font-size: 9pt;")
            row.addWidget(label)
            if prop.type == "bool":
                control = QPushButton("状态未知")
                control.setAutoDefault(False)
                control.setCheckable(True)
                control.setMinimumSize(76, 28)
                row.addStretch(1)
                control.clicked.connect(lambda checked, p=prop: self.session.request_write(p.name, checked))
            elif prop.value_list and not fan_speed:
                control = NoWheelCombo()
                control.setMinimumHeight(28)
                for item in prop.value_list:
                    control.addItem(str(item.get("desc_zh_cn") or item.get("description") or item["value"]), item["value"])
                control.activated.connect(lambda index, p=prop, c=control: self.session.request_write(p.name, c.itemData(index)))
                row.addStretch(1)
            elif scale is not None:
                color = self._accent if semantic == "brightness" or fan_speed else "#ff9b42"
                control = NoWheelSlider(Qt.Horizontal, color=color)
                control.setSegments(list(scale.segments))
                control.setRange(0, scale.count - 1)
                control.setSingleStep(1)
                self._scales[prop.name] = scale
                if self._primary_name is None and (semantic == "brightness" or fan_speed):
                    self._primary_name = prop.name
                control.valueChanged.connect(lambda index, p=prop, lbl=label, s=scale: self._preview(p, lbl, s, index))
                control.sliderPressed.connect(lambda c=control: self._begin_edit(c))
                control.committed.connect(lambda p=prop, c=control, s=scale: self._commit(p, c, s))
            else:
                line.deleteLater()
                continue
            control.setAccessibleName(f"{self.session.device.name} {prop.desc}")
            row.addWidget(control)
            self._body.addWidget(line)
            self._lines[prop.name] = line
            self._controls[prop.name] = (prop, control, label)
        self._apply_visibility()

    def _caption(self, prop, scale, value):
        if scale.index_of(value) is None:
            return "等待读数" if value is None else "未知档位"
        if scale.choices:
            return scale.label_for(value)
        semantic = _semantic(prop)
        if semantic == "brightness" and prop.range[1] <= 100:
            return f"{value:g}%"
        return f"{value:g} K" if semantic == "color-temperature" else f"{value:g}"

    def _preview(self, prop, label, scale, index):
        caption = self._caption(prop, scale, scale.value_at(index))
        label.setText(f"{_title(prop)}  {caption}")
        if prop.name == self._primary_name:
            self._summary.setText(caption)

    def _begin_edit(self, control):
        self._editing_control = control
        self.session.editing = True

    def _end_edit(self):
        if self._editing_control is not None:
            self._editing_control.setSliderDown(False)
            self._editing_control = None
            self.session.editing = False

    def _commit(self, prop, control, scale):
        self._end_edit()
        if control.isEnabled() and not control.isUnknown():
            self.session.request_write(prop.name, scale.value_at(control.value()))

    def hideEvent(self, event):
        self._end_edit()
        super().hideEvent(event)

    def _render(self):
        state = self.session
        signature = tuple((p.name, p.type, p.range, repr(p.value_list)) for p in state.props)
        if signature != self._signature:
            self._signature = signature
            self._build_controls()
        self._name.setText(state.device.name)
        self._retry.setEnabled(not state.busy and not state._inflight)
        stamp = state.updated_at.strftime("%H:%M:%S") if state.updated_at else "尚无读数"
        self.setToolTip(f"{state.device.room_name} · {state.message} · {stamp}")
        unknown = []
        for name, (prop, control, label) in self._controls.items():
            value = state.values.get(name)
            slider = isinstance(control, QSlider)
            if slider and control.isSliderDown() and state.device.online and state.presence_known:
                continue
            if slider and self._editing_control is control:
                self._end_edit()
            if slider and state.requested and state.requested[0] == name:
                value = state.requested[1]
            scale = self._scales.get(name)
            if slider:
                index = scale.index_of(value)
                valid = index is not None
                control.setUnknown(not valid)
            elif isinstance(control, QComboBox):
                index = control.findData(value) if value is not None else -1
                valid = index >= 0
            else:
                valid = isinstance(value, bool) or isinstance(value, (int, float)) and value in (0, 1)
            control.blockSignals(True)
            if control is self._power:
                control.set_online(state.device.online)
                control.set_busy(state.busy)
                control.set_state(bool(value) if valid else None)
                control.setChecked(bool(value) if valid else False)
            elif prop.type == "bool":
                control.setChecked(bool(value) if valid else False)
                control.setText("已开启" if valid and value else "已关闭" if valid else "状态未知")
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(index)
            elif slider:
                if valid:
                    control.setValue(index)
                label.setText(f"{_title(prop)}  {self._caption(prop, scale, value)}")
            control.blockSignals(False)
            control.setEnabled(state.device.online and state.presence_known and valid and
                               (slider or not state.busy and not state._inflight))
            if value is not None and not valid:
                unknown.append(prop.desc)
        if self._editing_control is None:
            if not state.device.online:
                summary = "离线"
            elif not state.presence_known:
                summary = "在线状态待确认"
            elif self._primary_name:
                prop = self._controls[self._primary_name][0]
                summary = self._caption(prop, self._scales[self._primary_name], state.values.get(self._primary_name))
            else:
                summary = state.device.room_name
            self._summary.setText(summary)
        self._state.setText("未识别的设备档位：" + "、".join(unknown) if unknown else state.message)
        self._state.setStyleSheet(f"color: {SiColors.ERROR_TEXT if state.error or unknown else SiColors.TEXT_SECONDARY}; font-size: 8pt;")
        self._state.setVisible(state.error or state.busy or bool(unknown))
        self._apply_visibility()
