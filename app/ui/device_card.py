# SPDX-License-Identifier: GPL-3.0-or-later
"""Flat Xiaomi-style tiles with capability-backed primary light/fan controls."""

from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.siui.components.container import SiRowCard
from app.core.models import DeviceInfo
from app.core.control_scale import ControlScale
from app.ui.filled_slider import FilledSlider
from app.ui.power_button import PowerButton
from app.ui.si_theme import SiColors

_POWER_BTN_SIZE = 30
_ICON_SIZE = 36
_CARD_FIXED_WIDTH = 300
_CARD_FIXED_HEIGHT = 114
_CARD_COMPACT_HEIGHT = 68


def _semantic(prop):
    return prop.semantic_name or prop.name.replace("_", "-")


class DeviceCard(SiRowCard):
    power_clicked = Signal(str)
    open_requested = Signal(str)

    def __init__(self, device: DeviceInfo, parent=None, session=None):
        super().__init__(parent, self.TopToBottom)
        self.device = device
        self.session = session
        self._busy = False
        self._hovered = False
        self._online = device.online
        self._press = None
        self._metrics = None
        self._power_state = None
        self._primary_prop = None
        self._primary_scale = None
        self._primary_signature = None
        self._edit_guard = {"active": False}
        self._is_light = ".light." in device.model or ":light:" in device.spec_type
        self._is_fan = ".fan." in device.model or ":fan:" in device.spec_type
        self._accent = "#ffbf00" if self._is_light else "#25b8b0" if self._is_fan else SiColors.THEME
        self.style_data.border_radius = 12.0
        self.style_data.background_color = QColor(SiColors.CARD)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(_CARD_FIXED_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.muteStretchWidget()

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._icon_label.setAlignment(Qt.AlignCenter)
        tint = QColor(self._accent)
        tint.setAlpha(48)
        self._icon_label.setStyleSheet(
            f"background: {tint.name(QColor.HexArgb)}; border: none; border-radius: 18px;")
        model = device.model
        symbol = ("mdi.lightbulb" if self._is_light else "mdi.fan" if self._is_fan else
                  "mdi.router-wireless" if ".router." in model else
                  "mdi.speaker" if "wifispeaker" in model else
                  "mdi.thermometer" if any(part in model for part in ("sensor_ht", ".sensor.", ".airmonitor.")) else
                  "mdi.devices")
        icon_color = self._accent if self._online else SiColors.ICON_DIM
        self._icon_label.setPixmap(qta.icon(symbol, color=icon_color).pixmap(22, 22))

        self._name_label = QLabel(device.name)
        self._name_label.setFont(QFont("Microsoft YaHei UI", 10, QFont.DemiBold))
        self._name_label.setWordWrap(False)
        self._name_label.setMinimumWidth(0)
        self._name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._name_label.setToolTip(device.name)
        self._name_label.setStyleSheet(
            f"color: {SiColors.TEXT_PRIMARY if self._online else SiColors.OFFLINE_TEXT};"
            "background: transparent; font-size: 10pt; font-weight: 600;")
        self._sub_label = QLabel(self._sub_text())
        self._sub_label.setStyleSheet(
            f"color: {SiColors.TEXT_SECONDARY}; background: transparent; font-size: 8pt;")
        text = QWidget()
        text.setMinimumWidth(0)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        text_layout.addWidget(self._name_label)
        text_layout.addWidget(self._sub_label)
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._power_btn = PowerButton(_POWER_BTN_SIZE, icon_size=19)
        self._power_btn.clicked.connect(lambda: self.power_clicked.emit(self.device.did))
        self._power_btn.set_online(self._online)
        self._power_btn.hide()
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self._icon_label)
        header.addWidget(text, 1)
        header.addWidget(self._power_btn)
        self._slider = FilledSlider(Qt.Horizontal, self, color=self._accent)
        self._slider.setEnabled(False)
        self._slider.setAccessibleName(device.name + (" 亮度" if self._is_light else " 风速"))
        self._slider.sliderPressed.connect(self._begin_edit)
        self._slider.valueChanged.connect(self._preview_value)
        self._slider.committed.connect(self._commit_value)
        layout = self.layout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._slider)
        slider_expected = session is not None and (self._is_light or self._is_fan)
        self._set_primary_visible(slider_expected)
        self.setToolTip(f"{device.name}\n{device.model}\n点击卡片查看全部功能")
        if session is not None:
            session.changed.connect(self._render_session)
            guard = self._edit_guard
            self.destroyed.connect(lambda: setattr(session, "editing", False) if guard["active"] else None)
            self._render_session()

    def _set_primary_visible(self, visible):
        self._slider.setVisible(visible)
        self.setFixedHeight(_CARD_FIXED_HEIGHT if visible else _CARD_COMPACT_HEIGHT)

    def _find_primary(self):
        if self.session is None:
            return None
        names = ("brightness",) if self._is_light else ("fan-level", "speed-level", "wind-speed", "speed")
        for name in names:
            for prop in self.session.props:
                if (_semantic(prop) == name and prop.readable and prop.writable
                        and ControlScale.from_prop(prop, segmented=self._is_fan) is not None):
                    return prop
        return None

    def power_prop(self):
        if self.session is None:
            return None
        return next((prop for prop in self.session.props if _semantic(prop) == "on" and prop.type == "bool"), None)

    def _render_session(self):
        state = self.session
        self.device = state.device
        self._online = state.device.online
        self._name_label.setText(state.device.name)
        self._name_label.setToolTip(state.device.name)
        prop = self._find_primary()
        self._primary_prop = prop
        scale = ControlScale.from_prop(prop, segmented=self._is_fan) if prop is not None else None
        self._primary_scale = scale
        signature = (prop.name, scale) if prop is not None else None
        if signature != self._primary_signature:
            self._primary_signature = signature
            self._slider.setSegments(list(scale.segments) if scale is not None else [])
            if scale is not None:
                self._slider.setRange(0, scale.count - 1)
        self._set_primary_visible(prop is not None or not state._loaded and (self._is_light or self._is_fan))
        value = state.values.get(prop.name) if prop is not None else None
        valid = scale is not None and scale.index_of(value) is not None
        can_control = self._online and state.presence_known and valid and prop is not None
        if not can_control and self._edit_guard["active"]:
            self._edit_guard["active"] = False
            state.editing = False
            self._slider.setSliderDown(False)
        self._slider.setEnabled(can_control)
        self._slider.setUnknown(not valid)
        if prop is not None and not self._slider.isSliderDown():
            requested = state.requested
            display = requested[1] if requested and requested[0] == prop.name else value
            index = scale.index_of(display)
            if index is not None:
                self._slider.blockSignals(True)
                self._slider.setValue(index)
                self._slider.blockSignals(False)
        power = self.power_prop()
        power_value = state.values.get(power.name) if power else None
        self._power_btn.setVisible(power is not None)
        self._power_btn.set_online(self._online)
        self._power_btn.set_busy(state.busy)
        self._power_btn.setEnabled(self._online and state.presence_known and power_value is not None
                                   and not state.busy and not state._inflight)
        if power_value is not None:
            self._power_state = bool(power_value)
            self._power_btn.set_state(bool(power_value))
        if not self._online:
            caption = "离线"
        elif not state.presence_known:
            caption = "在线状态待确认"
        elif state.error:
            caption = "状态读取失败" if not valid else self._value_text(value) + " · 同步失败"
        elif state.busy:
            caption = "设置中，等待设备确认…"
        elif prop is not None:
            caption = (self._value_text(value) if valid else "读取中…" if value is None else
                       "档位未知" if self._is_fan else "状态未知")
        elif not state._loaded:
            caption = "读取中…"
        else:
            caption = self._sub_text()
        if not self._slider.isSliderDown():
            self._sub_label.setText(caption)
        self._sub_label.setToolTip(state.message)
        self.update()

    def _value_text(self, value):
        if value is None:
            return "读取中…"
        if self._is_light:
            if self._primary_scale.choices:
                return "亮度 " + self._primary_scale.label_for(value)
            lo, hi, _ = self._primary_prop.range
            return f"{value:g}%" if 0 <= lo < hi <= 100 else f"亮度 {value:g}"
        return "风速 " + self._primary_scale.label_for(value)

    def _begin_edit(self):
        self._press = None
        if self.session is not None:
            self._edit_guard["active"] = True
            self.session.editing = True

    def _slider_value(self):
        return self._primary_scale.value_at(self._slider.value())

    def _preview_value(self, _index):
        if self._primary_prop is not None and self._slider.isSliderDown():
            self._sub_label.setText(self._value_text(self._slider_value()))

    def _commit_value(self):
        if self.session is None:
            return
        self._edit_guard["active"] = False
        self.session.editing = False
        if self._primary_prop is not None and self._slider.isEnabled():
            self.session.request_write(self._primary_prop.name, self._slider_value())

    def hideEvent(self, event) -> None:  # noqa: N802
        if self.session is not None and self._edit_guard["active"]:
            self._edit_guard["active"] = False
            self.session.editing = False
            self._slider.setSliderDown(False)
        super().hideEvent(event)

    def set_icon(self, path: Path | None) -> None:
        # Semantic light/fan icons retain the readable tinted badge from the tile.
        if self._is_light or self._is_fan or path is None or not path.is_file():
            return
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._icon_label.setPixmap(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_power_state(self, state: bool) -> None:
        if self.session is not None:
            self._render_session()
            return
        self._power_state = state
        self._power_btn.set_state(state)
        self._power_btn.setEnabled(self._online and not self._busy)
        self._power_btn.show()

    def _sub_text(self, metrics=None) -> str:
        if not self._online:
            return "离线"
        if metrics or self._metrics:
            return str(metrics or self._metrics)
        room = self.device.room_name
        return f"{room} · 在线" if room else "在线"

    def set_metrics(self, text: str | None) -> None:
        self._metrics = text
        if self.session is None:
            self._sub_label.setText(self._sub_text())

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._power_btn.set_busy(busy)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(SiColors.CARD_HOVER if self._hovered and self._online else
                                SiColors.CARD if self._online else SiColors.OFFLINE_CARD))
        painter.setPen(QPen(QColor(SiColors.CARD_BORDER_HOVER if self._hovered else SiColors.LINE), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is not None and (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._press = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        press, self._press = self._press, None
        if (event.button() == Qt.LeftButton and press is not None
                and (event.position().toPoint() - press).manhattanLength() < QApplication.startDragDistance()):
            self.open_requested.emit(self.device.did)
        super().mouseReleaseEvent(event)
