# SPDX-License-Identifier: GPL-3.0-or-later
"""Microphone protocol/cancellation checks never record or control devices."""

import json

import pytest
from PySide6.QtWidgets import QApplication

from app.core.speech import SpeechCapture, parse_speech_message
from app.ui.microphone_button import MicrophoneButton


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def wire(message):
    return json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"


class OutputProcess:
    def __init__(self):
        self.output = b""
        self.killed = False
        self.deleted = False

    def readAllStandardOutput(self):
        output, self.output = self.output, b""
        return output

    def kill(self):
        self.killed = True

    def deleteLater(self):
        self.deleted = True


def capture_with_output(qapp):
    capture = SpeechCapture()
    process = OutputProcess()
    capture._process = process
    capture._active = True
    return capture, process


@pytest.mark.parametrize("message", [
    {"type": "result", "text": "打开卧室灯", "confidence": 0.3},
    {"type": "result", "text": "打开卧室灯", "confidence": True},
    {"type": "result", "text": "   ", "confidence": 0.9},
    {"type": "result", "text": "打开卧室灯"},
    {"type": "command", "text": "打开卧室灯"},
    ["result", "打开卧室灯"],
])
def test_uncertain_or_malformed_result_cannot_become_a_command(message):
    with pytest.raises(ValueError):
        parse_speech_message(wire(message))


def test_fragmented_utf8_output_emits_exactly_one_command(qapp):
    capture, process = capture_with_output(qapp)
    commands, statuses = [], []
    capture.transcript.connect(commands.append)
    capture.status_changed.connect(statuses.append)
    result = wire({"type": "result", "text": "打开卧室灯", "confidence": 0.9})
    process.output = wire({"type": "ready"}) + result[:result.index("卧".encode()) + 1]
    capture._read_output()
    assert commands == []
    assert "聆听" in statuses[0]
    process.output = result[result.index("卧".encode()) + 1:]
    capture._finished()
    assert commands == ["打开卧室灯"]
    assert not capture.active
    assert process.deleted


def test_cancel_discards_a_result_already_in_child_pipe(qapp):
    capture, process = capture_with_output(qapp)
    commands, errors = [], []
    capture.transcript.connect(commands.append)
    capture.failed.connect(errors.append)
    process.output = wire({"type": "result", "text": "关闭灯", "confidence": 0.9})
    capture.cancel()
    capture._finished()
    assert process.killed
    assert commands == []
    assert errors == []
    assert not capture.active


def test_timeout_stops_child_and_reports_once(qapp):
    capture, process = capture_with_output(qapp)
    errors = []
    capture.failed.connect(errors.append)
    capture._timeout()
    capture._finished()
    assert process.killed
    assert len(errors) == 1
    assert "超时" in errors[0]


def test_engine_error_is_shown_and_never_submitted(qapp):
    capture, process = capture_with_output(qapp)
    commands, errors = [], []
    capture.transcript.connect(commands.append)
    capture.failed.connect(errors.append)
    process.output = wire({"type": "error", "text": "未安装中文语音组件"})
    capture._finished()
    assert errors == ["未安装中文语音组件"]
    assert commands == []


def test_microphone_button_second_click_cancels(qapp, monkeypatch):
    button = MicrophoneButton(compact=True)
    calls = []
    monkeypatch.setattr(button.capture, "start", lambda: calls.append("start"))
    button.click()
    button.capture._active = True
    monkeypatch.setattr(button.capture, "cancel", lambda: calls.append("cancel"))
    button.click()
    assert calls == ["start", "cancel"]
    button.capture._active = False
