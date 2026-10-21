# SPDX-License-Identifier: GPL-3.0-or-later
# MiHome-Windows: 米家设备的 Windows 桌面控制端
# Copyright (C) 2026 MiHome-Windows contributors
"""右下角电脑麦克风入口，识别普通话后交给小爱执行。

点击麦克风直接开始一次本地识别，旁边的键盘按钮保留文字指令。
监听状态、识别内容与执行反馈都在同一内联面板中显示。
"""

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

import qtawesome as qta

from app.ui.si_theme import SiColors
from app.ui.typewriter import TypewriterPlaceholder
from app.ui.microphone_button import MicrophoneButton

# 面板与球的观感尺寸：球为圆形，面板高度含上下留白恰好包住输入行
_BALL = 54
_PANEL_W = 380
_PANEL_H = 88
_GAP = 12
_MARGIN = 26

# 占位提示全文（打字节奏与停留时长在 typewriter 模块统一定义）
_HINT_FULL = "对小爱同学下指令，如“打开卧室灯”，回车执行"


class VoiceFab(QWidget):
    """悬浮球 + 内联指令面板；提交文本经 submitted 信号交给外部。"""

    submitted = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._expanded = False

        # ---- 内联输入面板（展开时显示，纯输入框回车提交） ----
        self._panel = QFrame(self)
        self._panel.setObjectName("voicePanel")
        outer = QVBoxLayout(self._panel)
        outer.setContentsMargins(14, 8, 14, 8)
        self._status_label = QLabel("对电脑说话，或输入指令后按回车", self._panel)
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)
        lay = QHBoxLayout()
        outer.addLayout(lay)
        self._edit = QLineEdit(self._panel)
        self._edit.setFont(QFont("Microsoft YaHei UI", 10))
        # 边框由面板承担，输入框本体保持透明避免双层描边
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {SiColors.TEXT_PRIMARY}; }}"
        )
        self._edit.installEventFilter(self)
        self._edit.returnPressed.connect(self._emit)
        lay.addWidget(self._edit)
        # 父控件 setVisible(True) 会连带显示所有未显式隐藏的子控件，
        # 面板必须在这里显式藏起，否则悬浮球首次显示时面板以默认
        # 几何露出一角
        self._panel.hide()

        # ---- 占位提示打字机动画：展开时逐字播放，停留后循环 ----
        self._typewriter = TypewriterPlaceholder(self._edit, _HINT_FULL)

        # ---- 圆形悬浮球 ----
        self._ball = MicrophoneButton(self, compact=True)
        self._ball.setObjectName("voiceBall")
        self._ball.setCursor(Qt.PointingHandCursor)
        self._ball.setIconSize(QSize(28, 28))
        self._ball.submitted.connect(self._recognized)
        self._ball.status_changed.connect(self._show_status)
        self._ball.failed.connect(self._recognition_error)
        self._text_button = QPushButton(self)
        self._text_button.setIcon(qta.icon('mdi.keyboard', color=SiColors.TEXT_SECONDARY))
        self._text_button.setToolTip("文字指令")
        self._text_button.setAccessibleName("输入小爱文字指令")
        self._text_button.setCursor(Qt.PointingHandCursor)
        self._text_button.clicked.connect(self._toggle)

        self.hide()
        self._apply_geometry()

    # ---------- 展开/收起 ----------

    def _toggle(self) -> None:
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        self._expanded = True
        self._apply_geometry()
        self._panel.show()
        self.raise_()
        self._edit.clear()
        self._edit.setFocus()
        self._typewriter.start()

    def collapse(self) -> None:
        self._ball.cancel()
        self._expanded = False
        self._typewriter.stop(clear=True)
        self._edit.clear()
        self._panel.hide()
        self._apply_geometry()

    # ---------- 占位提示打字机（动画实现见 typewriter 模块） ----------

    def _emit(self) -> None:
        text = self._edit.text().strip()
        if not text:
            self._edit.setFocus()
            return
        self.collapse()
        self.submitted.emit(text)

    def _show_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._expanded = True
        self._apply_geometry()
        self._panel.show()
        self.raise_()

    def _recognized(self, text: str) -> None:
        self._edit.setText(text)
        self.submitted.emit(text)

    def _recognition_error(self, text: str) -> None:
        self._show_status(text)
        self.failed.emit(text)

    def set_result(self, text: str) -> None:
        self._show_status(text)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名约定)
        # Esc 收起面板，不打断主窗口其余交互
        if obj is self._edit and event.type() == QEvent.KeyPress \
                and event.key() == Qt.Key_Escape:
            self.collapse()
            return True
        return super().eventFilter(obj, event)

    # ---------- 几何 ----------

    def reposition(self) -> None:
        """窗口尺寸变化后由宿主调用，保持贴右下角。"""
        self._apply_geometry()

    def retheme(self) -> None:
        """主题切换：输入面板底色/描边与文字颜色取当前调色板。"""
        from app.ui.si_theme import SiColors
        self._panel.setStyleSheet(
            f"QFrame#voicePanel {{ background: {SiColors.SURFACE};"
            f" border: 1px solid {SiColors.LINE}; border-radius: 12px; }}")
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {SiColors.TEXT_PRIMARY}; }}")
        self._status_label.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; background: transparent;")
        self._ball.retheme()
        self._text_button.setIcon(qta.icon('mdi.keyboard', color=SiColors.TEXT_SECONDARY))
        self._text_button.setStyleSheet(f"background: {SiColors.SURFACE}; border: 1px solid {SiColors.LINE}; border-radius: 14px;")

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt 命名约定)
        super().setVisible(visible)
        # central widget 创建晚于本控件会盖在上方，显示时置顶保证可点
        if visible:
            self.raise_()

    def _apply_geometry(self) -> None:
        host = self.parentWidget()
        w = min(_PANEL_W, max(240, host.width() - 2 * _MARGIN)) if self._expanded else _BALL + 42
        h = _BALL + ((_PANEL_H + _GAP) if self._expanded else 0)
        self.setGeometry(host.width() - _MARGIN - w,
                         host.height() - _MARGIN - h, w, h)
        # 球固定在容器右下角；收起时容器收缩为球自身大小，
        # 不遮挡下方网格卡片的点击
        self._ball.setGeometry(w - _BALL, h - _BALL, _BALL, _BALL)
        self._text_button.setGeometry(w - _BALL - 40, h - 42, 32, 32)
        if self._expanded:
            # 展开时容器宽度即面板宽度，面板占满容器、球叠在右下角
            self._panel.setGeometry(0, 0, w, _PANEL_H)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._ball.cancel()
        super().hideEvent(event)


