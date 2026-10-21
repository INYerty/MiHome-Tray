# SPDX-License-Identifier: GPL-3.0-or-later
"""Launch the verified setup package against the running application directory."""
from pathlib import Path
import re
import sys

from PySide6.QtCore import QProcess


def installer_command(installer: str) -> tuple[str, list[str]]:
    from app import is_packaged
    from app.core import _json_store
    if not is_packaged():
        raise RuntimeError("源码运行环境不执行安装；安装版支持应用内升级。")
    setup = Path(installer).resolve()
    update_root = (_json_store.data_dir() / "updates").resolve()
    if (not setup.is_file() or not setup.is_relative_to(update_root)
            or not re.fullmatch(r"MiHome-Tray-Setup-\d+\.\d+\.\d+-x64\.exe", setup.name)):
        raise RuntimeError("更新安装包路径无效，请重新下载。")
    executable = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve()
    target = executable.parent
    if executable.name.lower() != "mihome-tray.exe" or not executable.is_file() or not (target / "_internal").is_dir():
        raise RuntimeError("无法确认当前程序目录，已停止安装。")
    return str(setup), ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                        f"/DIR={target}", "/APPUPDATE=1"]


def start_installer(installer: str) -> None:
    executable, arguments = installer_command(installer)
    result = QProcess.startDetached(executable, arguments)
    started = result[0] if isinstance(result, tuple) else result
    if not started:
        raise RuntimeError("启动更新安装程序失败，当前程序仍可继续使用。")
