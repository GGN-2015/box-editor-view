from __future__ import annotations

import ctypes
import sys
from typing import Any


SW_MAXIMIZE = 3


def maximize_window(window: Any) -> bool:
    if sys.platform == "win32":
        return _maximize_windows_window(window)
    return _request_fullscreen_window(window)


def disable_ime_for_window(window: Any) -> bool:
    if sys.platform != "win32":
        return False

    hwnd = _window_handle_as_int(window)
    if not hwnd:
        return False

    try:
        imm32 = ctypes.WinDLL("imm32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except (AttributeError, OSError):
        return False

    if not _current_keyboard_layout_has_ime(user32, imm32):
        return False

    try:
        associate_context = imm32.ImmAssociateContext
        associate_context.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        associate_context.restype = ctypes.c_void_p
        associate_context(ctypes.c_void_p(hwnd), None)
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return True


def _current_keyboard_layout_has_ime(user32: Any, imm32: Any) -> bool:
    try:
        get_keyboard_layout = user32.GetKeyboardLayout
        get_keyboard_layout.argtypes = (ctypes.c_ulong,)
        get_keyboard_layout.restype = ctypes.c_void_p
        keyboard_layout = get_keyboard_layout(0)
        if not keyboard_layout:
            return False

        imm_is_ime = imm32.ImmIsIME
        imm_is_ime.argtypes = (ctypes.c_void_p,)
        imm_is_ime.restype = ctypes.c_bool
        return bool(imm_is_ime(keyboard_layout))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _window_handle_as_int(window: Any) -> int | None:
    if window is None or not hasattr(window, "getWindowHandle"):
        return None

    handle = window.getWindowHandle()
    if handle is None:
        return None

    for method_name in ("getIntHandle", "get_int_handle"):
        method = getattr(handle, method_name, None)
        if method is None:
            continue
        try:
            value = int(method())
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _maximize_windows_window(window: Any) -> bool:
    hwnd = _window_handle_as_int(window)
    if not hwnd:
        return _request_fullscreen_window(window)

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        show_window = user32.ShowWindow
        show_window.argtypes = (ctypes.c_void_p, ctypes.c_int)
        show_window.restype = ctypes.c_bool
        return bool(show_window(ctypes.c_void_p(hwnd), SW_MAXIMIZE))
    except (AttributeError, OSError, TypeError, ValueError):
        return _request_fullscreen_window(window)


def _request_fullscreen_window(window: Any) -> bool:
    if window is None or not hasattr(window, "requestProperties"):
        return False

    try:
        from panda3d.core import WindowProperties

        props = WindowProperties()
        props.setFullscreen(True)
        window.requestProperties(props)
    except Exception:
        return False
    return True
