# SPDX-License-Identifier: GPL-3.0-or-later
"""Use real glyph metrics even on Qt's fontless Windows offscreen platform."""
from pathlib import Path

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session", autouse=True)
def offscreen_fonts(qapp):
    if qapp.platformName() == "offscreen":
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            path = Path("C:/Windows/Fonts") / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
