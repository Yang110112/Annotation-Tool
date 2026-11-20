# -*- coding: utf-8 -*-
"""winutil.py —— Windows 相关的小工具"""
import ctypes
import os

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


def get_foreground_title():
    """获取当前最前面窗口的标题"""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def in_target_window(show=False):
    """当前窗口是否是标注页（每次都读 config.TARGET_KEYWORDS，GUI 修改关键词后立即生效）"""
    title = get_foreground_title()
    if show and config.DEBUG_TITLE:
        print("当前窗口标题：", title)
    return any(k in title for k in config.TARGET_KEYWORDS)