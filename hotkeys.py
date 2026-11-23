# -*- coding: utf-8 -*-
"""hotkeys.py —— GUI 版的鼠标键盘钩子逻辑（钩子线程里不要直接操作界面控件）"""
import ctypes

from pynput import keyboard, mouse

import actions
from settings import ACTIONS, MOUSE_NAMES, WHEEL_CODES
from winutil import in_target_window, WM_MOUSEWHEEL

# 鼠标 / 键盘消息常量
WM_MOUSEMOVE = 0x0200
MOUSE_DOWN = {0x0201: "left", 0x0204: "right", 0x0207: "middle"}
MOUSE_UP = {0x0202: "left", 0x0205: "right", 0x0208: "middle"}
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
KEY_DOWN_MSGS = (0x0100, 0x0104)   # WM_KEYDOWN, WM_SYSKEYDOWN
KEY_UP_MSGS = (0x0101, 0x0105)     # WM_KEYUP, WM_SYSKEYUP
VK_ESCAPE = 0x1B
CTRL_VKS = (0xA2, 0xA3)            # 左 Ctrl / 右 Ctrl：单按一下作为一种特殊按键（code 为 "ctrl"）
CTRL_BINDING = {"type": "key", "code": "ctrl", "name": "Ctrl（单按）"}


class HotkeyManager:
    def __init__(self, q, bindings, suppress):
        self.q = q                    # 往界面线程发事件的队列
        self.bindings = bindings
        self.suppress = suppress
        self.enabled = False          # 是否在监听
        self.recording = None         # 正在录入哪个功能："auto" / "replay" / "speed" / None
        self.held = set()             # 键盘按住状态，防止长按连续触发
        self.sup_mouse = set()        # 按下时被拦截的鼠标键，抬起时必须同样拦截
        self.sup_keys = set()         # 按下时被拦截的键盘键，抬起时必须同样拦截
        self.ctrl_keys = set()        # 当前按住的 Ctrl 键
        self.ctrl_clean = False       # 本次 Ctrl 按下期间，是否没有按过其他键 / 鼠标
        # 钩子一直挂着（录入按键也需要），是否触发由 self.enabled 控制
        self.mouse_listener = mouse.Listener(win32_event_filter=self.on_mouse)
        self.keyboard_listener = keyboard.Listener(win32_event_filter=self.on_key)

    def start(self):
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def stop(self):
        self.mouse_listener.stop()
        self.keyboard_listener.stop()

    # ---------- 工具 ----------
    @staticmethod
    def describe(b):
        if not b:
            return "（未设置）"
        return ("鼠标：" if b["type"] == "mouse" else "键盘：") + b["name"]

    @staticmethod
    def conflict(a, b):
        if not a or not b or a["type"] != b["type"]:
            return False
        if a["code"] == b["code"]:
            return True
        if a["type"] == "mouse":
            return a["code"] in WHEEL_CODES and b["code"] in WHEEL_CODES and "wheel_any" in (a["code"], b["code"])
        return False

    @staticmethod
    def key_name(data):
        lparam = (data.scanCode << 16) | ((data.flags & 0x01) << 24)
        buf = ctypes.create_unicode_buffer(64)
        n = ctypes.windll.user32.GetKeyNameTextW(lparam, buf, 64)
        return buf.value if n else f"VK_{data.vkCode}"

    def match(self, typ, codes):
        for action in ACTIONS:
            b = self.bindings.get(action)
            if b and b["type"] == typ and b["code"] in codes:
                return action
        return None

    def finish_record(self, b):
        action = self.recording
        self.recording = None
        self.q.put(("record", action, b))

    def trigger(self, action, is_wheel, label="触发键"):
        if action == "auto":
            actions.start_auto(label)
        elif action == "replay":
            actions.start_replay(label, is_wheel)
        elif action == "speed":
            actions.start_speed(label)

    # ---------- 钩子回调 ----------
    def on_mouse(self, msg, data):
        if msg == WM_MOUSEMOVE:
            return True
        if data.flags & 0x01:      # 程序自己（pyautogui）模拟的事件，直接放行，避免死循环
            return True

        if msg in MOUSE_DOWN:
            kind, codes = "down", (MOUSE_DOWN[msg],)
        elif msg in MOUSE_UP:
            kind, codes = "up", (MOUSE_UP[msg],)
        elif msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            which = "x1" if ((data.mouseData >> 16) & 0xFFFF) == 1 else "x2"
            kind, codes = ("down" if msg == WM_XBUTTONDOWN else "up"), (which,)
        elif msg == WM_MOUSEWHEEL:
            delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
            direction = "wheel_up" if delta > 0 else "wheel_down"
            kind, codes = "wheel", (direction, "wheel_any")
        else:
            return True

        # Ctrl 按住期间有鼠标操作（点击 / 滚轮）：这次 Ctrl 不算"单按"
        if self.ctrl_keys and kind in ("down", "wheel"):
            self.ctrl_clean = False

        if self.recording:
            if kind in ("down", "wheel"):
                code = codes[0]
                self.finish_record({"type": "mouse", "code": code, "name": MOUSE_NAMES[code]})
            return True

        # 抬起：按下时被拦截过，抬起就同样拦截（成对处理），不再判断窗口
        if kind == "up":
            if codes[0] in self.sup_mouse:
                self.sup_mouse.discard(codes[0])
                self.mouse_listener.suppress_event()
            return True

        if not self.enabled:
            return True

        action = self.match("mouse", codes)
        if not action:
            return True
        # 不在标注页：直接放行，其他程序里该按键功能完全正常
        if not in_target_window(show=(kind == "down")):
            return True
        self.trigger(action, kind == "wheel")
        if self.suppress:
            if kind == "down":
                self.sup_mouse.add(codes[0])
            self.mouse_listener.suppress_event()
        return True

    def on_key(self, msg, data):
        if data.flags & 0x10:      # 程序自己模拟的按键（如 ctrl+c / ctrl+v），直接放行
            return True
        if msg in KEY_DOWN_MSGS:
            down = True
        elif msg in KEY_UP_MSGS:
            down = False
        else:
            return True
        vk = data.vkCode

        if down and vk == VK_ESCAPE:
            if self.recording:
                self.recording = None
                self.q.put(("record_cancel",))
            elif self.enabled:
                self.q.put(("stop",))
            return True

        if self.recording:
            if down:
                if vk in CTRL_VKS:
                    # 录入时按下 Ctrl：记为"Ctrl 单按"（左右 Ctrl 通用）
                    self.finish_record(dict(CTRL_BINDING))
                else:
                    self.finish_record({"type": "key", "code": vk, "name": self.key_name(data)})
            return True

        # Ctrl 键：单按一下（按下 -> 松开，期间没按其他键）触发已绑定到 "Ctrl（单按）" 的功能
        # 在标注页内才生效；不拦截 Ctrl，页面里的 Ctrl+C / Ctrl+A 等组合键不受影响
        if vk in CTRL_VKS:
            if down:
                if not self.ctrl_keys:    # 第一次按下（长按的重复事件不重新判断）
                    self.ctrl_clean = self.enabled and in_target_window(show=True)
                self.ctrl_keys.add(vk)
            else:
                self.ctrl_keys.discard(vk)
                if not self.ctrl_keys:    # 所有 Ctrl 都松开了
                    was_clean = self.ctrl_clean
                    self.ctrl_clean = False
                    if was_clean and self.enabled and in_target_window():
                        action = self.match("key", ("ctrl",))
                        if action:
                            self.trigger(action, False, "Ctrl")
            return True

        # Ctrl 按住期间按了别的键（组合键）：不算单按
        if down and self.ctrl_keys:
            self.ctrl_clean = False

        # 抬起：始终清除按住状态；按下时被拦截过的，抬起同样拦截
        if not down:
            self.held.discard(vk)
            if vk in self.sup_keys:
                self.sup_keys.discard(vk)
                self.keyboard_listener.suppress_event()
            return True

        if not self.enabled:
            return True

        action = self.match("key", (vk,))
        if not action:
            return True
        if not in_target_window(show=True):
            return True
        if vk not in self.held:
            self.held.add(vk)
            self.trigger(action, False)
        if self.suppress:
            self.sup_keys.add(vk)
            self.keyboard_listener.suppress_event()
        return True