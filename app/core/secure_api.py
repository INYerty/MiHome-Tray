# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows account sessions encrypted for the current Windows user with DPAPI."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time

from mijiaAPI import mijiaAPI
from requests.adapters import HTTPAdapter

from app.core import _json_store


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise OSError("登录凭据加密需要 Windows DPAPI")
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(source), "MiHome Tray account", None, None, None, 1, ctypes.byref(output))
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class _TimeoutAdapter(HTTPAdapter):
    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (5, 12)
        return super().send(request, **kwargs)


class SecureMijiaAPI(mijiaAPI):
    def __init__(self, auth_path: Path | None = None):
        path = auth_path or _json_store.data_dir() / "account.dpapi"
        # Initialize upstream protocol configuration without reading its shared
        # plaintext CLI account. This app requires its own explicit QR login.
        super().__init__(auth_data_path=str(path.parent / ".unused-account-path"))
        self.auth_data_path = path
        self.auth_data = {}
        self.locale = "zh_CN"
        self.service_login_url = "https://account.xiaomi.com/pass/serviceLogin?_json=true&sid=mijia&_locale=zh_CN"
        if path.exists():
            try:
                self.auth_data = json.loads(protect(path.read_bytes(), decrypt=True).decode("utf-8"))
                self._init_session()
            except (OSError, ValueError, KeyError, TypeError):
                self.auth_data = {}  # Keep the unreadable file; next QR login replaces it.

    def _init_session(self):
        super()._init_session()
        self.session.mount("https://", _TimeoutAdapter())

    def _save_auth_data(self):
        self.auth_data["saveTime"] = int(time.time() * 1000)
        payload = protect(json.dumps(self.auth_data, ensure_ascii=False).encode("utf-8"))
        self.auth_data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.auth_data_path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, self.auth_data_path)
