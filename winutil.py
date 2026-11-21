# -*- coding: utf-8 -*-
"""winutil.py —— Windows 相关的小工具"""
import ctypes
import os
import threading
import time

import config

# Windows 鼠标 / 键盘消息常量
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
LLKHF_INJECTED = 0x10       # 程序模拟的按键（如 pyautogui 发出的 ctrl+c），需要忽略
VK_TAB = 0x09


def get_desktop_path():
    """获取真实桌面路径（兼容桌面被 OneDrive 重定向的情况）"""
    try:
        buf = ctypes.create_unicode_buffer(260)
        # 0x10 = CSIDL_DESKTOPDIRECTORY
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
        if buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


# ====== 前台窗口标题：后台线程缓存，钩子里只读缓存 ======
_cached_title = ""
_updater_started = False
_start_lock = threading.Lock()


def _title_updater():
    """后台线程：定时读取前台窗口标题。
    即使目标窗口（如 Edge）卡住，也只卡这个线程，不会拖住鼠标/键盘钩子。"""
    global _cached_title
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    # InternalGetWindowText 不向对方窗口发消息，不会因对方无响应而阻塞
    getter = getattr(user32, "InternalGetWindowText", None) or user32.GetWindowTextW
    getter.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    buf = ctypes.create_unicode_buffer(512)
    while True:
        try:
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                buf[0] = "\0"
                getter(hwnd, buf, 512)
                _cached_title = buf.value
            else:
                _cached_title = ""
        except Exception:
            pass
        time.sleep(0.05)


def _ensure_updater():
    global _updater_started
    if _updater_started:
        return
    with _start_lock:
        if not _updater_started:
            threading.Thread(target=_title_updater, daemon=True).start()
            _updater_started = True


def get_foreground_title():
    """读缓存的前台窗口标题（可在钩子里安全调用）"""
    _ensure_updater()
    return _cached_title


def in_target_window(show=False):
    """当前窗口是否是标注页（每次都读 config.TARGET_KEYWORDS，GUI 修改关键词后立即生效）"""
    title = get_foreground_title()
    if show and config.DEBUG_TITLE:
        print("当前窗口标题：", title)
    return any(k in title for k in config.TARGET_KEYWORDS)


_ensure_updater()   # 导入时就启动，保证第一次触发前缓存已有值