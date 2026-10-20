# SPDX-License-Identifier: GPL-3.0-or-later
"""Initialize streams before importing libraries in a windowed executable."""

import os
from pathlib import Path
import sys


def ensure_gui_streams():
    # PyInstaller --windowed and pythonw set streams to None. mijiaAPI's
    # formatter calls stdout.isatty() during import, before a GUI can appear.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        try:
            folder = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MiHome-Windows" / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            sys.stderr = (folder / "app.log").open("a", encoding="utf-8", buffering=1)
        except OSError:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
