# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows 11 system Acrylic, shared by the main window and tray flyout.

Uses documented DWM attributes. No desktop capture, simulated blur or injection.
Qt keeps a native frame (with its title area removed by WM_NCCALCSIZE), so the
backing store can be composed by DWM instead of UpdateLayeredWindow.
"""
import ctypes
from ctypes import wintypes
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from app.ui.si_theme import SiColors, is_dark

logger = logging.getLogger(__name__)


def supported():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22621


def tint(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def card_color(hover=False):
    c = QColor(SiColors.CARD_HOVER if hover else SiColors.CARD)
    c.setAlpha(180 if hover else 135)
    return c


def prepare_glass(window):
    window.setObjectName("glassWindow")
    if supported():
        window.setAttribute(Qt.WA_TranslucentBackground, True)
        palette = window.palette()
        palette.setColor(QPalette.Window, QColor(0, 0, 0, 0))
        window.setPalette(palette)
    window.setProperty("glassActive", False)


def apply_glass(window):
    if not supported():
        return False
    class Margins(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]
    try:
        dwm = ctypes.WinDLL("dwmapi")
        attr = dwm.DwmSetWindowAttribute
        attr.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        attr.restype = ctypes.c_long
        extend = dwm.DwmExtendFrameIntoClientArea
        extend.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        extend.restype = ctypes.c_long
        hwnd = int(window.winId())
        # The app supplies its own title buttons. With a transparent title area,
        # DWM would otherwise reveal the native caption buttons underneath.
        user = ctypes.WinDLL("user32", use_last_error=True)
        get_style = user.GetWindowLongPtrW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style = user.SetWindowLongPtrW
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        style = get_style(hwnd, -16)
        if style & 0x00080000:  # WS_SYSMENU (keep native resize/maximize styles)
            set_style(hwnd, -16, style & ~0x00080000)
            position = user.SetWindowPos
            position.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
            position(hwnd, None, 0, 0, 0, 0, 0x0037)  # FRAMECHANGED, NOMOVE, NOSIZE, NOACTIVATE, NOZORDER
        class BlurBehind(ctypes.Structure):
            _fields_ = [("flags", wintypes.DWORD), ("enable", wintypes.BOOL),
                        ("region", wintypes.HRGN), ("transition", wintypes.BOOL)]
        blur = dwm.DwmEnableBlurBehindWindow
        blur.argtypes = [wintypes.HWND, ctypes.POINTER(BlurBehind)]
        blur.restype = ctypes.c_long
        # QWidget's raster backing store needs its alpha channel opted in to
        # DWM composition; otherwise transparent pixels become solid black.
        blur_data = BlurBehind(1, True, None, False)
        blur(hwnd, ctypes.byref(blur_data))
        def set_value(key, value):
            data = ctypes.c_int(value)
            return attr(hwnd, key, ctypes.byref(data), ctypes.sizeof(data))
        set_value(20, int(is_dark()))  # DWMWA_USE_IMMERSIVE_DARK_MODE
        set_value(33, 2)  # DWMWCP_ROUND
        margins = Margins(-1, -1, -1, -1)
        frame_result = extend(hwnd, ctypes.byref(margins))
        result = set_value(38, 3)  # DWMSBT_TRANSIENTWINDOW / desktop Acrylic
        active = result == 0 and frame_result == 0
        window.setProperty("glassActive", active)
        # Only this window's background changes; child widgets keep their styles.
        window.setStyleSheet(f"QWidget#glassWindow {{ background: {'transparent' if active else SiColors.WINDOW_BG}; }}")
        if not active:
            logger.warning("系统毛玻璃未启用，使用主题背景: %s / %s", result, frame_result)
        return active
    except (OSError, AttributeError) as exc:
        logger.warning("系统毛玻璃初始化失败: %s", exc)
        window.setStyleSheet(f"QWidget#glassWindow {{ background: {SiColors.WINDOW_BG}; }}")
        return False
