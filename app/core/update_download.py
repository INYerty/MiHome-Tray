# SPDX-License-Identifier: GPL-3.0-or-later
"""Download and verify official installer assets; never execute an installer."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urljoin, urlsplit

import requests
from PySide6.QtCore import QObject, Signal

from app.core._json_store import data_dir
from app.core.update_checker import ReleaseInfo, release_asset_url, release_version

_MAX_INSTALLER = 1024 * 1024 * 1024
_MAX_CHECKSUMS = 64 * 1024
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


class UpdateCancelled(RuntimeError):
    pass


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise UpdateCancelled("已取消更新下载")


def _open_asset(url: str, cancel: threading.Event):
    """Follow GitHub's signed CDN redirects without accepting arbitrary hosts."""
    from app import __version__

    original = url
    for _ in range(6):
        _check_cancel(cancel)
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment
                or (parsed.hostname == "github.com" and url != original)):
            raise RuntimeError("安装包下载被重定向到了不受信任的地址")
        response = requests.get(
            url, stream=True, allow_redirects=False, timeout=(5, 15),
            headers={"User-Agent": f"MiHome-Tray/{__version__}", "Accept-Encoding": "identity"})
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RuntimeError("下载服务器没有提供有效地址")
            url = urljoin(url, location)
            continue
        try:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError("下载服务器未返回完整文件")
        except Exception:
            response.close()
            raise
        return response
    raise RuntimeError("下载服务器重定向次数过多")


def _expected_digest(manifest: bytes, filename: str) -> str:
    """Accept standard sha256sum text, with one exact installer filename only."""
    try:
        text = manifest.decode("utf-8-sig")
    except UnicodeError as error:
        raise RuntimeError("SHA256 校验文件编码无效") from error
    matches = []
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if match and match.group(2) == filename:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise RuntimeError("SHA256 校验文件缺少唯一匹配的安装包记录")
    return matches[0]


def download_release(info: ReleaseInfo, cancel: threading.Event, progress=None) -> Path:
    """Synchronous worker entry point, also usable with isolated mocked tests."""
    version = release_version(info.tag)
    filename = f"MiHome-Tray-Setup-{version}-x64.exe"
    if not info.installer_url or not info.installer_name:
        raise RuntimeError("此版本没有 Windows x64 安装包，无法在应用内更新")
    if not info.checksum_url:
        raise RuntimeError("此版本缺少 SHA256SUMS.txt 校验文件，无法安全更新")
    if (info.installer_name != filename or info.installer_url != release_asset_url(info.tag, filename)
            or info.checksum_url != release_asset_url(info.tag, "SHA256SUMS.txt")):
        raise RuntimeError("安装包或校验文件不属于当前项目的正式发布")
    if isinstance(info.size, bool) or not isinstance(info.size, int) or not 0 < info.size <= _MAX_INSTALLER:
        raise RuntimeError("安装包大小信息无效，请重新检查更新")
    _check_cancel(cancel)
    response = _open_asset(info.checksum_url, cancel)
    try:
        chunks, length = [], 0
        for chunk in response.iter_content(chunk_size=8192):
            _check_cancel(cancel)
            if not chunk:
                continue
            length += len(chunk)
            if length > _MAX_CHECKSUMS:
                raise RuntimeError("SHA256 校验文件异常过大")
            chunks.append(chunk)
        digest = _expected_digest(b"".join(chunks), filename)
    finally:
        response.close()
    directory = data_dir() / "updates" / version
    directory.mkdir(parents=True, exist_ok=True)
    part = None
    try:
        _check_cancel(cancel)
        response = _open_asset(info.installer_url, cancel)
        try:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except ValueError as error:
                    raise RuntimeError("安装包长度信息无效") from error
                if declared_size != info.size:
                    raise RuntimeError("安装包大小与发布信息不一致")
            with tempfile.NamedTemporaryFile(prefix=filename + ".", suffix=".part", dir=directory, delete=False) as stream:
                part = Path(stream.name)
                hasher, received = hashlib.sha256(), 0
                if progress is not None:
                    progress(0, info.size)
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    _check_cancel(cancel)
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > info.size:
                        raise RuntimeError("安装包长度超出发布信息")
                    stream.write(chunk)
                    hasher.update(chunk)
                    if progress is not None:
                        progress(received, info.size)
                _check_cancel(cancel)
                if received != info.size:
                    raise RuntimeError("安装包下载不完整，请重试")
                if hasher.hexdigest() != digest:
                    raise RuntimeError("安装包 SHA256 校验失败，请重新下载")
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            response.close()
        _check_cancel(cancel)
        destination = directory / filename
        os.replace(part, destination)
        part = None
        return destination
    finally:
        if part is not None:
            part.unlink(missing_ok=True)


class UpdateDownloader(QObject):
    progress = Signal(int, int)
    finished = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, info: ReleaseInfo) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._cancel = threading.Event()
        threading.Thread(target=self._run, args=(info,), daemon=True, name="MiHome-Update").start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self, info: ReleaseInfo) -> None:
        path, error = "", None
        try:
            path = str(download_release(info, self._cancel, self.progress.emit))
        except Exception as failure:
            error = failure
        with self._lock:
            self._running = False
        self.finished.emit(path, error)
