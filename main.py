# -*- coding: utf-8 -*-
"""main.py —— 命令行版入口：右键 = 自动化，滚轮 = 重听，Tab = 倍速切换"""
import ctypes

from pynput import keyboard, mouse

import actions
import config
from mima import unlock
from winutil import (WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MOUSEWHEEL, WM_KEYDOWN, WM_KEYUP,
                     LLKHF_INJECTED, VK_TAB, in_target_window)

mouse_listener = None
keyboard_listener = None


# 鼠标事件过滤：只在标注页窗口内，右键 = 自动化，滚轮 = 重听，并拦截对应事件
def win32_event_filter(msg, data):
    if msg in (WM_RBUTTONDOWN, WM_RBUTTONUP):
        # 不在标注页：直接放行，右键菜单等功能完全正常
        if not in_target_window(show=(msg == WM_RBUTTONDOWN)):
            return True
        if msg == WM_RBUTTONDOWN:
            actions.start_auto("鼠标右键")
        mouse_listener.suppress_event()

    elif msg == WM_MOUSEWHEEL:
        # 不在标注页：直接放行，其他程序里滚轮正常滚动
        if not in_target_window():
            return True
        actions.start_replay("滚轮滚动", is_wheel=True)
        if config.SUPPRESS_WHEEL:
            mouse_listener.suppress_event()

    return True


# 键盘事件过滤：只在标注页窗口内，Tab = 切换 1.25 / 1 倍速
def keyboard_event_filter(msg, data):
    if msg not in (WM_KEYDOWN, WM_KEYUP):
        return True
    # 忽略程序模拟出来的按键
    if data.flags & LLKHF_INJECTED:
        return True
    if data.vkCode != VK_TAB:
        return True

    # 带 Alt / Ctrl / Shift / Win 的组合键（如 Alt+Tab）直接放行
    get_state = ctypes.windll.user32.GetAsyncKeyState
    if any(get_state(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
        return True

    # 不在标注页：直接放行
    if not in_target_window():
        return True

    if msg == WM_KEYDOWN:
        actions.start_speed("Tab")

    # 拦截 Tab，避免页面焦点跳动
    keyboard_listener.suppress_event()
    return True


def on_release(key):
    # 按 esc 停止监听
    if key == keyboard.Key.esc:
        print("停止监听")
        mouse_listener.stop()
        return False


def main():
    global mouse_listener, keyboard_listener

    if not unlock():
        exit()

    actions.init()
    print("✅ 已设置触发键：鼠标右键 = 自动化，滚轮 = 重听音频，Tab = 1.25 / 1 倍速切换（仅在标注页窗口内生效）")

    mouse_listener = mouse.Listener(win32_event_filter=win32_event_filter)
    keyboard_listener = keyboard.Listener(
        on_release=on_release,
        win32_event_filter=keyboard_event_filter,
    )
    mouse_listener.start()
    keyboard_listener.start()
    print("监听已启动，右键执行自动化，滚轮重听音频，Tab 切换 1.25/1 倍速，ESC 退出监听")
    keyboard_listener.join()


if __name__ == "__main__":
    main()