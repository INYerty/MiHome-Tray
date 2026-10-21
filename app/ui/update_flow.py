# SPDX-License-Identifier: GPL-3.0-or-later
# MiHome-Windows: 米家设备的 Windows 桌面控制端
# Copyright (C) 2026 MiHome-Windows contributors
"""版本检查的界面流程：发起检查 → 有新版本弹对话框，否则按场景反馈。

自动（启动时）与手动（关于页/设置入口）共用这一条链路，仅反馈策略
不同：自动检查在「无新版本」与「网络失败」时完全静默，不打扰
用户；手动检查两种情况都要给出明确回显，否则用户无法区分
「没新版」与「断网了」。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from app.core.update_checker import UpdateChecker, is_newer
from app.ui.toast import Toast

_active_dialog = None


def check_update(parent, manual: bool) -> None:
    """发起一次检查；parent 用于挂 checker 与弹对话框。"""
    checker = UpdateChecker(parent)

    def _finish(info, error) -> None:
        checker.deleteLater()
        if error is not None:
            if manual:
                Toast.info(parent, f"检查更新失败：{error}", 4000)
            return
        from app import __version__
        if info is None or not is_newer(info.tag, __version__):
            if manual:
                Toast.info(parent, "当前已是最新版本", 2500)
            return
        prompt_new_version(parent, info)

    checker.check_finished.connect(_finish)
    checker.check()


def prompt_new_version(parent, info) -> None:
    """One user confirmation covers download, verification, install and restart."""
    global _active_dialog
    if _active_dialog is not None:
        _active_dialog.raise_()
        _active_dialog.activateWindow()
        return
    host = None if parent is not None and parent.isHidden() else parent
    dialog = UpdateDialog(info, host)
    _active_dialog = dialog
    try:
        dialog.exec()
    finally:
        _active_dialog = None
        dialog.deleteLater()


class UpdateDialog(QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        from app import __version__, is_packaged
        from app.core.update_download import UpdateDownloader
        self.info = info
        self._verified_path = ""
        self._cancel_requested = False
        self._downloader = UpdateDownloader(self)
        self._downloader.progress.connect(self._progress)
        self._downloader.finished.connect(self._finished)
        self.setWindowTitle("更新米家快捷控制")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(450)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        title = QLabel(f"发现新版本 {info.tag}")
        title.setStyleSheet("font-size: 16pt; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"当前版本 v{__version__} · {info.name}"))
        self._status = QLabel("下载并校验后，将关闭当前程序进行安装，完成后自动重新打开。\n账号、设备收藏和个人设置会保留。")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout.addWidget(self._bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self._cancel = QPushButton("暂不更新")
        self._cancel.clicked.connect(self.reject)
        row.addWidget(self._cancel)
        self._install = QPushButton("下载并安装")
        self._install.setMinimumSize(120, 34)
        self._install.clicked.connect(self._start)
        row.addWidget(self._install)
        layout.addLayout(row)
        if not getattr(info, "installer_url", "") or not getattr(info, "checksum_url", ""):
            self._status.setText("此发布缺少安装包或校验文件，暂时无法在应用内安装。")
            self._install.setEnabled(False)
        elif not is_packaged():
            self._status.setText("当前是源码运行环境；安装版可在此下载、校验并完成升级。")
            self._install.setEnabled(False)

    def _start(self):
        if self._verified_path:
            self._install_verified()
            return
        self._cancel_requested = False
        self._install.setEnabled(False)
        self._cancel.setText("取消下载")
        self._status.setText("正在下载更新安装包…")
        self._bar.setValue(0)
        self._downloader.start(self.info)

    def _progress(self, received, total):
        if self._cancel_requested:
            return
        if total > 0:
            self._bar.setValue(min(99, round(received / total * 100)))
        self._status.setText(f"正在下载：{received / 1048576:.1f} / {total / 1048576:.1f} MB")

    def _finished(self, path, error):
        from app.core.update_download import UpdateCancelled
        if self._cancel_requested or isinstance(error, UpdateCancelled):
            super().reject()
            return
        self._cancel.setText("关闭")
        self._cancel.setEnabled(True)
        if error is not None:
            self._status.setText(f"更新未完成：{error}\n可稍后重试，当前版本仍可使用。")
            self._install.setEnabled(True)
            return
        self._verified_path = path
        self._bar.setValue(100)
        self._install_verified()

    def _install_verified(self):
        from app.core.update_install import start_installer
        try:
            start_installer(self._verified_path)
        except Exception as error:
            self._status.setText(str(error))
            self._install.setText("重试安装")
            self._install.setEnabled(True)
            return
        self._status.setText("校验通过，正在启动安装程序…")
        app = QApplication.instance()
        if app is not None:
            for window in app.topLevelWidgets():
                if hasattr(window, "request_force_quit"):
                    window.request_force_quit()
            app.closeAllWindows()
            app.quit()

    def reject(self):
        if self._downloader.running:
            self._cancel_requested = True
            self._cancel.setEnabled(False)
            self._status.setText("正在取消下载…")
            self._downloader.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self._downloader.running:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
