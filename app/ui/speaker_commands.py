# SPDX-License-Identifier: GPL-3.0-or-later
"""Account-device-specific saved directives, shared by dashboard and flyout."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)
import shiboken6

from app.core import settings_store
from app.ui.si_theme import SiColors


class SpeakerCommands(QFrame):
    def __init__(self, service, jobs, device, parent=None):
        super().__init__(parent)
        self._service, self._jobs, self.device = service, jobs, device
        self._action = None
        self._loaded = False
        self._busy = False
        self._editing = None
        self.setObjectName("speakerCommands")
        self.retheme()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        header = QHBoxLayout()
        header.addWidget(QLabel("小爱 · 自定义指令"), 1)
        self._add = QPushButton("＋ 添加")
        self._add.setAutoDefault(False)
        self._add.clicked.connect(lambda: self._edit_command(None))
        header.addWidget(self._add)
        outer.addLayout(header)
        self._status = QLabel("正在读取此音箱的指令能力…")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; font-size: 9pt;")
        outer.addWidget(self._status)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(6)
        outer.addLayout(self._rows)
        self._editor = QFrame()
        form = QVBoxLayout(self._editor)
        form.setContentsMargins(0, 4, 0, 0)
        self._title = QLineEdit()
        self._title.setPlaceholderText("按钮名称，例如：晚安")
        self._text = QLineEdit()
        self._text.setPlaceholderText("实际指令，例如：关闭卧室灯")
        for edit in (self._title, self._text):
            edit.setMinimumWidth(0)
            form.addWidget(edit)
        actions = QHBoxLayout()
        save = QPushButton("保存指令")
        save.setAutoDefault(False)
        save.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self._editor.hide)
        actions.addWidget(save)
        actions.addWidget(cancel)
        form.addLayout(actions)
        self._text.returnPressed.connect(self._save)
        outer.addWidget(self._editor)
        self._editor.hide()
        self._render()

    def retheme(self):
        self.setStyleSheet(
            f"QFrame#speakerCommands {{ background: {SiColors.CARD}; border: 1px solid {SiColors.LINE}; border-radius: 16px; }}"
            f"QLabel {{ background: transparent; color: {SiColors.TEXT_PRIMARY}; border: none; }}"
            f"QPushButton {{ background: {SiColors.SURFACE}; color: {SiColors.TEXT_PRIMARY}; border: none; border-radius: 8px; padding: 6px 10px; }}"
            f"QPushButton:hover {{ background: {SiColors.BTN_HOVER}; }}")
        if hasattr(self, "_status"):
            self._status.setStyleSheet(f"color: {SiColors.TEXT_SECONDARY}; font-size: 9pt;")
            self._render()

    def showEvent(self, event):
        super().showEvent(event)
        self._render()  # Another view may have edited these commands.
        if not self._loaded:
            self._loaded = True
            self._jobs.submit(lambda: self._service.device_detail(self.device.did),
                              on_success=self._capabilities, on_error=self._failed)

    def _capabilities(self, detail):
        if not shiboken6.isValid(self):
            return
        self._action = next((a.name for a in detail.actions
                             if a.name == "execute-text-directive"), None)
        self._status.setText("点击指令直接交给这台音箱执行" if self._action else
                             "此型号未公开文本指令能力，已保存指令仍可编辑")
        self._render()

    def _render(self):
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        commands = settings_store.get_speaker_commands(self.device.did)
        for index, command in enumerate(commands):
            line = QFrame()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            run = QPushButton(command["title"])
            run.setToolTip(command["text"])
            run.setAutoDefault(False)
            run.setEnabled(bool(self._action) and self.device.online and not self._busy)
            run.clicked.connect(lambda _, c=command: self._run(c))
            row.addWidget(run, 1)
            for label, tip, callback in (
                ("↑", "上移", lambda _, i=index: self._move(i, -1)),
                ("↓", "下移", lambda _, i=index: self._move(i, 1)),
                ("编辑", "编辑指令", lambda _, i=index: self._edit_command(i)),
                ("×", "删除指令", lambda _, i=index: self._delete(i)),
            ):
                button = QPushButton(label)
                button.setAutoDefault(False)
                button.setToolTip(tip)
                button.setAccessibleName(tip + command["title"])
                button.clicked.connect(callback)
                if label in ("↑", "↓", "×"):
                    button.setFixedWidth(28)
                if label == "↑":
                    button.setEnabled(index > 0)
                elif label == "↓":
                    button.setEnabled(index < len(commands) - 1)
                row.addWidget(button)
            self._rows.addWidget(line)

    def _edit_command(self, index):
        self._editing = index
        items = settings_store.get_speaker_commands(self.device.did)
        item = items[index] if index is not None and index < len(items) else {"title": "", "text": ""}
        self._title.setText(item["title"])
        self._text.setText(item["text"])
        self._editor.show()
        self._title.setFocus()

    def _save(self):
        title, text = self._title.text().strip(), self._text.text().strip()
        if not title or not text:
            self._status.setText("请填写按钮名称和实际指令")
            return
        items = settings_store.get_speaker_commands(self.device.did)
        item = {"title": title, "text": text}
        if self._editing is not None and self._editing < len(items):
            items[self._editing] = item
        else:
            items.append(item)
        settings_store.set_speaker_commands(self.device.did, items)
        self._editor.hide()
        self._status.setText("指令已保存")
        self._render()

    def _move(self, index, delta):
        items = settings_store.get_speaker_commands(self.device.did)
        target = index + delta
        if 0 <= index < len(items) and 0 <= target < len(items):
            items[index], items[target] = items[target], items[index]
            settings_store.set_speaker_commands(self.device.did, items)
            self._editor.hide()
            self._render()

    def _delete(self, index):
        items = settings_store.get_speaker_commands(self.device.did)
        if 0 <= index < len(items):
            items.pop(index)
            settings_store.set_speaker_commands(self.device.did, items)
            self._editor.hide()
            self._render()

    def _run(self, command):
        if not self._action or self._busy or not self.device.online:
            return
        self._busy = True
        self._status.setText(f"正在发送：{command['text']}")
        self._render()
        self._jobs.submit(lambda: self._service.run_action(self.device.did, self._action, [command["text"]]),
                          on_success=lambda _: self._done(command), on_error=self._failed)

    def _done(self, command):
        if shiboken6.isValid(self):
            self._busy = False
            self._status.setText(f"已发送：{command['text']}（以设备实际响应为准）")
            self._render()

    def _failed(self, error):
        if shiboken6.isValid(self):
            self._busy = False
            self._status.setText(f"操作失败：{error}")
            self._render()
