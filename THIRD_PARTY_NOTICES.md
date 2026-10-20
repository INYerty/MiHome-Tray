# Third-party notices

MiHome Tray is a GPL-3.0-or-later derivative of
[huanyuejue/MiHome-Windows](https://github.com/huanyuejue/MiHome-Windows),
baseline `22655b8d0df07da44772833fbd33f696c0629b17`.
Original source headers, license and Git history are retained.

- mijiaAPI: [source](https://github.com/Do1e/mijia-api), GPL-3.0-or-later.
- PySide6-SiliconUI: [source](https://github.com/H1DDENADM1N/PySide6-SiliconUI),
  GPL-3.0; the vendored component's license is `app/siui/LICENSE`.
- Qt for Python / PySide6 / Shiboken: LGPL-3.0-only OR GPL-2.0-only OR
  GPL-3.0-only. This GPL application bundles dynamically loaded Qt libraries.
  [Sources and releases](https://download.qt.io/official_releases/QtForPython/).
- CPython: Python Software Foundation License;
  [source releases](https://www.python.org/downloads/source/).
- Inno Setup Simplified Chinese messages: MIT, copyright kirakira;
  [source](https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation),
  pinned at `1ff90acc4ed4aee82b1cda43253243deee3daed4`.
  The original file header and `packaging/languages/LICENSE` are retained.

Python dependencies and exact versions are listed in `requirements-lock.txt`.
Available installed dependency license files are copied to
`third-party-licenses/` in the binary distribution. The matching application
source is included as `MiHome-Tray-source.zip` and published in GitHub Releases.
Build instructions and scripts are in that source archive.

The installer is produced with [Inno Setup](https://jrsoftware.org/), using its
unmodified compiler and standard installer runtime.
