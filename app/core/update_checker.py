# SPDX-License-Identifier: GPL-3.0-or-later
# MiHome-Windows: 米家设备的 Windows 桌面控制端
# Copyright (C) 2026 MiHome-Windows contributors
"""GitHub Releases 新版本检查：取最新 release 版本号与当前版本对比。

检查走独立后台线程而非 JobExecutor 串行队列：这是与米家无关的第三方
请求，混进设备任务队列会让弱网下最长十几秒的超时连带阻塞设备加载与
用户操作。结果经信号发回主线程，界面线程永不受网络等待影响。
"""

import re
import threading
from dataclasses import dataclass

import requests
from PySide6.QtCore import QObject, Signal

_REPO = "INYerty/MiHome-Tray"
LATEST_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{_REPO}/releases/latest"


@dataclass
class ReleaseInfo:
    tag: str
    url: str
    name: str
    installer_url: str = ""
    installer_name: str = ""
    checksum_url: str = ""
    size: int = 0


def release_version(tag: str) -> str:
    """Only stable numeric tags can select executable assets or local folders."""
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", tag)
    if match is None or len(tag) > 64:
        raise RuntimeError("更新版本号无效，仅支持正式版本")
    return match.group(1)


def release_asset_url(tag: str, filename: str) -> str:
    release_version(tag)
    return f"https://github.com/{_REPO}/releases/download/{tag}/{filename}"


def fetch_latest_release() -> ReleaseInfo:
    """拉取仓库最新 release；网络失败/响应异常都抛异常由调用方处理。"""
    from app import __version__

    resp = requests.get(
        LATEST_API,
        timeout=(5, 8),
        headers={
            "User-Agent": f"MiHome-Windows/{__version__}",
            "Accept": "application/vnd.github+json",
        },
        allow_redirects=False,
    )
    resp.raise_for_status()
    if resp.status_code != 200:
        raise RuntimeError("版本检查服务器返回了意外的重定向")
    data = resp.json()
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise RuntimeError("未找到可用的正式版本")
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("最新版本信息缺少版本号")
    version = release_version(tag)
    installer_name = f"MiHome-Tray-Setup-{version}-x64.exe"
    assets = data.get("assets") or []
    if not isinstance(assets, list):
        raise RuntimeError("更新资源信息无效")
    selected = {}
    for filename in (installer_name, "SHA256SUMS.txt"):
        matches = [asset for asset in assets
                   if isinstance(asset, dict) and asset.get("name") == filename]
        if len(matches) > 1:
            raise RuntimeError("更新资源存在重名，无法安全选择安装包")
        if matches:
            asset = matches[0]
            if asset.get("browser_download_url") != release_asset_url(tag, filename):
                raise RuntimeError("更新资源地址不属于当前项目的正式发布")
            selected[filename] = asset
    installer = selected.get(installer_name)
    size = installer.get("size", 0) if installer else 0
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise RuntimeError("更新安装包大小无效")
    return ReleaseInfo(
        tag=tag,
        url=f"https://github.com/{_REPO}/releases/tag/{tag}",
        name=str(data.get("name") or tag),
        installer_url=release_asset_url(tag, installer_name) if installer else "",
        installer_name=installer_name if installer else "",
        checksum_url=release_asset_url(tag, "SHA256SUMS.txt") if "SHA256SUMS.txt" in selected else "",
        size=size,
    )


def _version_parts(value: str) -> tuple[int, ...]:
    """版本号解析为数字段：容忍 v 前缀、预发布/构建后缀与非数字段。"""
    core = value.strip().lower().lstrip("v")
    core = re.split(r"[-+].*$", core)[0]
    parts: list[int] = []
    for seg in core.split("."):
        m = re.match(r"\d+", seg)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新；位数不等时按 0 补齐再逐段比较。"""
    a = list(_version_parts(latest))
    b = list(_version_parts(current))
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return tuple(a) > tuple(b)


class UpdateChecker(QObject):
    """后台线程查一次最新版本；check_finished 回主线程（info, error）。"""

    check_finished = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def check(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            info = fetch_latest_release()
        except Exception as exc:  # 网络异常全部转回调，绝不打崩进程
            self.check_finished.emit(None, exc)
        else:
            self.check_finished.emit(info, None)
