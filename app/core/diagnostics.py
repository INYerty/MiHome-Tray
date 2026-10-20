# SPDX-License-Identifier: GPL-3.0-or-later
"""Retain Qt fatal messages and Python stacks for native runtime failures."""
import faulthandler
import os
import sys

from PySide6.QtCore import QtMsgType, qInstallMessageHandler


def _qt_message(kind, context, message):
    if kind not in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        return
    try:
        sys.stderr.write(f"Qt[{kind.name}]: {message}\n")
        sys.stderr.flush()
    except (OSError, AttributeError):
        pass


def install_runtime_diagnostics():
    # Windows COM uses handled native exceptions for normal control flow.
    # Enable the verbose native handler only for an explicit diagnostic run.
    if os.environ.get("MIHOME_NATIVE_DIAGNOSTICS") == "1":
        try:
            faulthandler.enable(file=sys.stderr, all_threads=True)
        except (OSError, AttributeError):
            pass
    qInstallMessageHandler(_qt_message)
