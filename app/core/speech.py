# SPDX-License-Identifier: GPL-3.0-or-later
"""One-shot, local Windows Mandarin dictation without extra runtimes or keys.

Windows' installed System.Speech recognizer runs in a hidden child process so
microphone initialization and recognition never block the Qt event loop. Audio
is neither saved nor sent by this module. The resulting text follows the same
XiaoAI action path as a manually typed command.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import weakref

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import QApplication


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$engine = $null
function Send-Message($message) {
    [Console]::WriteLine(($message | ConvertTo-Json -Compress))
    [Console]::Out.Flush()
}
try {
    Add-Type -AssemblyName System.Speech
    $info = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
        Where-Object { $_.Culture.Name -eq 'zh-CN' } | Select-Object -First 1
    if ($null -eq $info) {
        Send-Message @{type='error'; text='未安装中文语音识别。请在 Windows 设置 → 时间和语言 → 语言和区域中安装中文（简体，中国）的语音组件。'}
        exit 2
    }
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($info)
    $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
    $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(5)
    $engine.BabbleTimeout = [TimeSpan]::FromSeconds(10)
    $engine.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(700)
    $engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromMilliseconds(900)
    $engine.SetInputToDefaultAudioDevice()
    Send-Message @{type='ready'}
    $result = $engine.Recognize([TimeSpan]::FromSeconds(12))
    if ($null -eq $result) {
        Send-Message @{type='error'; text='没有听清，请检查默认麦克风后再试。'}
    } elseif ($result.Confidence -lt 0.55) {
        Send-Message @{type='error'; text=('识别不确定，未执行：' + $result.Text + '。请重试或使用文字输入。')}
    } else {
        Send-Message @{type='result'; text=$result.Text; confidence=$result.Confidence}
    }
} catch {
    Send-Message @{type='error'; text=('麦克风识别不可用：' + $_.Exception.Message + '。请检查 Windows 麦克风权限、默认输入设备与中文语音组件。')}
} finally {
    if ($null -ne $engine) { $engine.Dispose() }
}
"""


def parse_speech_message(line: bytes) -> dict:
    """Validate the small UTF-8 line protocol before a command can be emitted."""
    message = json.loads(line.decode("utf-8-sig"))
    if not isinstance(message, dict) or message.get("type") not in {"ready", "result", "error"}:
        raise ValueError("无效的语音识别响应")
    if message["type"] != "ready":
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("语音识别没有返回有效内容")
        message["text"] = text.strip()
    if message["type"] == "result":
        confidence = message.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not 0.55 <= confidence <= 1:
            raise ValueError("识别不确定，请重新说一遍或使用文字输入")
    return message


class SpeechCapture(QObject):
    """One click starts; a second cancels. Only one capture may own the mic."""

    transcript = Signal(str)
    status_changed = Signal(str)
    failed = Signal(str)
    active_changed = Signal(bool)
    _owner: weakref.ReferenceType | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None
        self._buffer = b""
        self._done = False
        self._active = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._process is not None:
            return
        if os.name != "nt":
            self.failed.emit("电脑语音控制需要 Windows 中文语音组件。")
            return
        owner = SpeechCapture._owner() if SpeechCapture._owner is not None else None
        if owner is not None and owner.active:
            self.failed.emit("另一个窗口正在使用麦克风，请先结束或取消。")
            return
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if not executable.is_file():
            self.failed.emit("未找到 Windows PowerShell，无法启动本地语音识别。")
            return
        self._buffer = b""
        self._done = False
        process = QProcess(self)
        self._process = process
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        SpeechCapture._owner = weakref.ref(self)
        self._active = True
        self.active_changed.emit(True)
        self.status_changed.emit("正在启动麦克风…再次点击取消")
        encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
        process.start(str(executable), ["-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded])
        self._timer.start(22000)

    def cancel(self) -> None:
        if self._process is None:
            return
        self._done = True
        self._timer.stop()
        self._process.kill()
        self._set_inactive()
        self.status_changed.emit("已取消语音输入")

    def shutdown(self) -> None:
        process = self._process
        self.cancel()
        if process is not None:
            process.waitForFinished(1000)

    def _set_inactive(self) -> None:
        if self._active:
            self._active = False
            self.active_changed.emit(False)

    def _read_output(self) -> None:
        if self._process is None:
            return
        self._buffer += bytes(self._process.readAllStandardOutput())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if not line.strip() or self._done:
                continue
            try:
                message = parse_speech_message(line)
            except (ValueError, UnicodeError):
                self._fail("语音识别返回了无效内容，请重新尝试。")
                continue
            if message["type"] == "ready":
                self.status_changed.emit("正在聆听，请说普通话…再次点击取消")
            elif message["type"] == "result":
                self._done = True
                self._timer.stop()
                self._set_inactive()
                self.status_changed.emit("正在执行：" + message["text"])
                self.transcript.emit(message["text"])
            else:
                self._fail(message["text"])

    def _fail(self, text: str) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self._set_inactive()
        if self._process is not None:
            self._process.kill()
        self.failed.emit(text)

    def _timeout(self) -> None:
        self._fail("语音识别超时，请检查麦克风后重试。")
        if self._process is not None:
            self._process.kill()

    def _process_error(self, _error) -> None:
        self._fail("无法启动语音识别，请检查 Windows 中文语音组件与麦克风权限。")
        if self._process is not None and self._process.state() == QProcess.NotRunning:
            self._finished()

    def _finished(self, *_args) -> None:
        self._read_output()
        self._fail("语音识别提前结束，请检查麦克风后重试。")
        self._timer.stop()
        self._set_inactive()
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
