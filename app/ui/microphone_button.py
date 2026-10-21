# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable one-click microphone for both the dashboard and tray popup."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QPushButton
import qtawesome as qta

from app.core.speech import SpeechCapture
from app.ui.si_theme import SiColors


class MicrophoneButton(QPushButton):
    submitted = Signal(str)
    status_changed = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.setAutoDefault(False)
        self._compact = compact
        self.capture = SpeechCapture(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("电脑麦克风语音控制")
        self.setIconSize(QSize(21, 21))
        self.setMinimumSize(36, 36)
        self.clicked.connect(self.toggle_capture)
        self.capture.transcript.connect(self.submitted)
        self.capture.status_changed.connect(self._status)
        self.capture.failed.connect(self._error)
        self.capture.active_changed.connect(lambda _: self.retheme())
        self.retheme()

    def toggle_capture(self) -> None:
        if self.capture.active:
            self.capture.cancel()
        else:
            self.capture.start()

    @property
    def listening(self) -> bool:
        return self.capture.active

    def is_listening(self) -> bool:
        return self.capture.active

    def cancel(self) -> None:
        self.capture.cancel()

    def _status(self, text: str) -> None:
        self.setToolTip(text)
        self.status_changed.emit(text)

    def _error(self, text: str) -> None:
        self.setToolTip(text)
        self.failed.emit(text)

    def retheme(self) -> None:
        active = self.capture.active
        self.setText("" if self._compact else ("取消聆听" if active else "语音控制"))
        self.setIcon(qta.icon("mdi.stop" if active else "mdi.microphone", color=SiColors.WHITE if active else SiColors.THEME))
        self.setStyleSheet(
            f"QPushButton {{ background: {SiColors.DANGER if active else SiColors.SURFACE};"
            f"color: {SiColors.TEXT_PRIMARY}; border: 1px solid {SiColors.THEME};"
            "border-radius: 12px; padding: 6px; }"
            f"QPushButton:hover {{ border-color: {SiColors.THEME_HOVER}; }}"
        )
        self.setToolTip("再次点击取消聆听" if active else "点击后对电脑说话，普通话识别并交给小爱执行")

    def hideEvent(self, event) -> None:  # noqa: N802
        self.cancel()
        super().hideEvent(event)
