# -*- coding: utf-8 -*-
"""
gui.py —— 标注自动化助手（可视化界面）
不修改 mima.py 和原主脚本，只在外面包一层界面。
运行方式：python gui.py
"""
import ctypes
import importlib
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from pynput import keyboard, mouse

import mima  # 原密码模块，不做任何修改

# ====== 需要你确认的配置 ======
# 原主脚本的文件名（不带 .py）。如果你的主脚本不叫 main.py，改这里
SCRIPT_MODULE = "main"
# ==============================

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hotkey_config.json")
FONT = ("Microsoft YaHei UI", 10)

# Windows 鼠标 / 键盘消息常量
WM_MOUSEMOVE = 0x0200
MOUSE_DOWN = {0x0201: "left", 0x0204: "right", 0x0207: "middle"}
MOUSE_UP = {0x0202: "left", 0x0205: "right", 0x0208: "middle"}
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEWHEEL = 0x020A
KEY_DOWN_MSGS = (0x0100, 0x0104)   # WM_KEYDOWN, WM_SYSKEYDOWN
KEY_UP_MSGS = (0x0101, 0x0105)     # WM_KEYUP, WM_SYSKEYUP
VK_ESCAPE = 0x1B

MOUSE_NAMES = {
    "left": "左键",
    "right": "右键",
    "middle": "中键",
    "x1": "侧键1（后退）",
    "x2": "侧键2（前进）",
    "wheel_up": "滚轮向上",
    "wheel_down": "滚轮向下",
    "wheel_any": "滚轮（上下均可）",
}
WHEEL_CODES = {"wheel_up", "wheel_down", "wheel_any"}

# 默认按键 = 你原来的设定：右键 = 自动化，滚轮 = 重听
DEFAULT_BINDINGS = {
    "auto": {"type": "mouse", "code": "right", "name": MOUSE_NAMES["right"]},
    "replay": {"type": "mouse", "code": "wheel_any", "name": MOUSE_NAMES["wheel_any"]},
}


class QueueWriter:
    """把 print 输出转到队列，由界面线程显示到日志框"""

    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s and s.strip():
            self.q.put(("log", s.rstrip()))
        return len(s) if s else 0

    def flush(self):
        pass


# ====================== 密码窗口 ======================
def password_dialog():
    """图形化版本的 mima.unlock()，返回 True 表示解锁成功"""
    if mima.is_unlocked():
        return True

    result = {"ok": False, "tries": 0}
    root = tk.Tk()
    root.title("解锁")
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=22)
    frm.pack()
    ttk.Label(frm, text="需要解锁才能使用本程序", font=("Microsoft YaHei UI", 12, "bold")).pack(pady=(0, 10))
    info = tk.StringVar(value=f"请输入密码（剩余尝试次数：{mima.MAX_RETRY}）")
    ttk.Label(frm, textvariable=info, font=FONT).pack(anchor="w")
    entry = ttk.Entry(frm, show="●", width=30, font=FONT)
    entry.pack(pady=8)
    entry.focus_set()
    err = tk.Label(frm, text="", fg="red", font=FONT)
    err.pack()

    def submit(event=None):
        pwd = entry.get()
        if mima.get_hash(pwd) == mima.PASSWORD_HASH:
            with open(mima.FLAG_FILE, "w", encoding="utf-8") as f:
                f.write("unlocked")
            result["ok"] = True
            messagebox.showinfo("解锁成功", "✅ 解锁成功！以后启动不再需要输入密码")
            root.destroy()
        else:
            result["tries"] += 1
            left = mima.MAX_RETRY - result["tries"]
            if left <= 0:
                messagebox.showerror("解锁失败", "⛔ 次数用尽，解锁失败，程序退出")
                root.destroy()
            else:
                err.config(text=f"❌ 密码错误，还剩 {left} 次机会")
                info.set(f"请输入密码（剩余尝试次数：{left}）")
                entry.delete(0, "end")

    btns = ttk.Frame(frm)
    btns.pack(pady=(10, 0))
    ttk.Button(btns, text="解锁", command=submit).pack(side="left", padx=6)
    ttk.Button(btns, text="退出", command=root.destroy).pack(side="left", padx=6)
    root.bind("<Return>", submit)

    root.eval("tk::PlaceWindow . center")
    root.mainloop()
    return result["ok"]


# ====================== 主界面 ======================
class App:
    def __init__(self, auto_mod, log_q):
        self.auto = auto_mod          # 原主脚本模块
        self.q = log_q                # 日志 + 事件队列
        self.recording = None         # 正在录入哪个功能："auto" / "replay" / None
        self.enabled = False          # 是否在监听
        self.held = set()             # 键盘按住状态，防止长按连续触发
        self.bindings = dict(DEFAULT_BINDINGS)
        self.suppress = True
        keywords = list(getattr(self.auto, "TARGET_KEYWORDS", []))
        self.load_config(keywords)

        self.root = tk.Tk()
        self.root.title("标注自动化助手")
        self.root.geometry("680x600")
        self.build_ui()

        self.auto.TARGET_KEYWORDS = self.parse_keywords()

        # 钩子一直挂着（录入按键也需要），是否触发由 self.enabled 控制
        self.mouse_listener = mouse.Listener(win32_event_filter=self.on_mouse)
        self.keyboard_listener = keyboard.Listener(win32_event_filter=self.on_key)
        self.mouse_listener.start()
        self.keyboard_listener.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---------- 配置 ----------
    def load_config(self, default_keywords):
        cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        self.bindings = {
            "auto": cfg.get("auto") or DEFAULT_BINDINGS["auto"],
            "replay": cfg.get("replay") or DEFAULT_BINDINGS["replay"],
        }
        self.keywords_init = cfg.get("keywords") or default_keywords
        self.suppress = bool(cfg.get("suppress", True))

    def save_config(self):
        cfg = {
            "auto": self.bindings["auto"],
            "replay": self.bindings["replay"],
            "keywords": self.parse_keywords(),
            "suppress": self.suppress,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("⚠️ 保存配置失败：", e)

    # ---------- 界面 ----------
    def build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        self.status_var = tk.StringVar()
        self.status_lbl = tk.Label(main, textvariable=self.status_var, font=("Microsoft YaHei UI", 11, "bold"), anchor="w")
        self.status_lbl.pack(fill="x")

        box = ttk.LabelFrame(main, text="触发按键（点“设置按键”后，按下想用的键盘键 / 鼠标键 / 滚轮）", padding=10)
        box.pack(fill="x", pady=10)
        self.bind_vars, self.bind_btns = {}, {}
        rows = (("auto", "自动化（提取编号 + 点击 + 粘贴）"), ("replay", "重听音频"))
        for i, (action, title) in enumerate(rows):
            ttk.Label(box, text=title, font=FONT, width=28).grid(row=i, column=0, sticky="w", pady=6)
            var = tk.StringVar()
            ttk.Label(box, textvariable=var, font=FONT, width=24, relief="groove", anchor="center").grid(row=i, column=1, padx=8)
            btn = ttk.Button(box, text="设置按键", command=lambda a=action: self.start_record(a))
            btn.grid(row=i, column=2)
            self.bind_vars[action], self.bind_btns[action] = var, btn
        ttk.Label(box, text="提示：Esc 可取消录入；监听中按 Esc 会暂停监听", foreground="gray").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.refresh_binding_text()

        opt = ttk.LabelFrame(main, text="其他设置", padding=10)
        opt.pack(fill="x")
        ttk.Label(opt, text="目标窗口标题关键词（多个用逗号分隔）：", font=FONT).grid(row=0, column=0, sticky="w")
        self.kw_var = tk.StringVar(value="，".join(self.keywords_init))
        ttk.Entry(opt, textvariable=self.kw_var, width=34, font=FONT).grid(row=0, column=1, padx=8, sticky="w")
        self.suppress_var = tk.BooleanVar(value=self.suppress)
        self.suppress_var.trace_add("write", lambda *a: setattr(self, "suppress", self.suppress_var.get()))
        ttk.Checkbutton(opt, text="在标注页内拦截触发键（不再传给页面，和原脚本行为一致）",
                        variable=self.suppress_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=12)
        self.toggle_btn = ttk.Button(bar, text="▶ 开始监听", command=self.toggle)
        self.toggle_btn.pack(side="left")
        ttk.Button(bar, text="恢复默认按键", command=self.reset_default).pack(side="left", padx=10)
        ttk.Button(bar, text="清空日志", command=self.clear_log).pack(side="left")

        logf = ttk.LabelFrame(main, text="运行日志", padding=6)
        logf.pack(fill="both", expand=True)
        self.log = tk.Text(logf, height=12, state="disabled", font=("Consolas", 9), wrap="word")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.update_status()

    def describe(self, b):
        if not b:
            return "（未设置）"
        return ("鼠标：" if b["type"] == "mouse" else "键盘：") + b["name"]

    def refresh_binding_text(self):
        for action in ("auto", "replay"):
            self.bind_vars[action].set(self.describe(self.bindings.get(action)))

    def update_status(self):
        if self.recording:
            self.status_var.set("● 请按下想要的按键…（Esc 取消）")
            self.status_lbl.config(fg="#d97706")
        elif self.enabled:
            self.status_var.set("● 监听中（仅在标注页窗口内生效）")
            self.status_lbl.config(fg="#16a34a")
        else:
            self.status_var.set("● 已暂停（点击“开始监听”启用）")
            self.status_lbl.config(fg="gray")

    def append_log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 500:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.config(state="disabled")

    def clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # ---------- 按钮动作 ----------
    def parse_keywords(self):
        raw = self.kw_var.get().replace("，", ",")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def toggle(self):
        if self.recording:
            return
        if not self.enabled:
            kws = self.parse_keywords()
            if not kws:
                messagebox.showwarning("提示", "目标窗口关键词不能为空，否则任何窗口都不会触发。")
                return
            self.auto.TARGET_KEYWORDS = kws
            self.save_config()
        self.set_enabled(not self.enabled)

    def set_enabled(self, value):
        self.enabled = value
        self.held.clear()
        self.toggle_btn.config(text="■ 暂停监听" if value else "▶ 开始监听")
        self.update_status()
        print("监听已启动" if value else "监听已暂停")

    def reset_default(self):
        if self.recording:
            return
        self.bindings = dict(DEFAULT_BINDINGS)
        self.refresh_binding_text()
        self.save_config()

    def start_record(self, action):
        if self.recording:
            return
        self.held.clear()
        self.recording = action
        for b in self.bind_btns.values():
            b.config(state="disabled")
        self.toggle_btn.config(state="disabled")
        self.update_status()

    def end_record_ui(self):
        for b in self.bind_btns.values():
            b.config(state="normal")
        self.toggle_btn.config(state="normal")
        self.update_status()

    @staticmethod
    def conflict(a, b):
        if not a or not b or a["type"] != b["type"]:
            return False
        if a["code"] == b["code"]:
            return True
        if a["type"] == "mouse":
            return a["code"] in WHEEL_CODES and b["code"] in WHEEL_CODES and "wheel_any" in (a["code"], b["code"])
        return False

    def on_recorded(self, action, b):
        self.end_record_ui()
        other = "replay" if action == "auto" else "auto"
        if self.conflict(b, self.bindings.get(other)):
            messagebox.showwarning("按键冲突", "这个按键已被另一个功能使用，请换一个。")
            return
        if b["type"] == "mouse" and b["code"] == "left" and self.suppress:
            if not messagebox.askyesno(
                    "确认",
                    "你选了鼠标左键，并且开启了“拦截触发键”。\n"
                    "这样在标注页里左键将无法正常点击页面。\n\n仍要使用吗？"):
                return
        self.bindings[action] = b
        self.refresh_binding_text()
        self.save_config()
        print(f"已设置：{'自动化' if action == 'auto' else '重听音频'} = {self.describe(b)}")

    def on_record_cancel(self):
        self.end_record_ui()

    # ---------- 队列轮询（在界面线程里处理钩子线程发来的事件） ----------
    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.append_log(item[1])
                elif kind == "record":
                    self.on_recorded(item[1], item[2])
                elif kind == "record_cancel":
                    self.on_record_cancel()
                elif kind == "stop":
                    self.set_enabled(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---------- 钩子线程：以下代码不要直接操作界面控件 ----------
    def match(self, typ, codes):
        for action in ("auto", "replay"):
            b = self.bindings.get(action)
            if b and b["type"] == typ and b["code"] in codes:
                return action
        return None

    def finish_record(self, b):
        action = self.recording
        self.recording = None
        self.q.put(("record", action, b))

    def trigger(self, action, is_wheel):
        a = self.auto
        if action == "auto":
            if not a.auto_running:
                a.auto_running = True
                print("检测到触发键，开始执行自动化！")
                threading.Thread(target=a.run_task, daemon=True).start()
        else:
            if a.replay_running:
                return
            if is_wheel:
                now = time.time()
                if now - a.last_wheel_time <= a.WHEEL_COOLDOWN:
                    return
                a.last_wheel_time = now
            a.replay_running = True
            print("检测到触发键，重听音频！")
            threading.Thread(target=a.replay_audio, daemon=True).start()

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

        if self.recording:
            if kind in ("down", "wheel"):
                code = codes[0]
                self.finish_record({"type": "mouse", "code": code, "name": MOUSE_NAMES[code]})
            return True
        if not self.enabled:
            return True

        action = self.match("mouse", codes)
        if not action:
            return True
        # 不在标注页：直接放行，其他程序里该按键功能完全正常
        if not self.auto.in_target_window(show=(kind == "down")):
            return True
        if kind in ("down", "wheel"):
            self.trigger(action, kind == "wheel")
        if self.suppress:
            self.mouse_listener.suppress_event()
        return True

    @staticmethod
    def key_name(data):
        lparam = (data.scanCode << 16) | ((data.flags & 0x01) << 24)
        buf = ctypes.create_unicode_buffer(64)
        n = ctypes.windll.user32.GetKeyNameTextW(lparam, buf, 64)
        return buf.value if n else f"VK_{data.vkCode}"

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
                self.finish_record({"type": "key", "code": vk, "name": self.key_name(data)})
            return True
        if not self.enabled:
            return True

        action = self.match("key", (vk,))
        if not action:
            return True
        if not down:
            self.held.discard(vk)
        if not self.auto.in_target_window(show=down):
            return True
        if down and vk not in self.held:
            self.held.add(vk)
            self.trigger(action, False)
        if self.suppress:
            self.keyboard_listener.suppress_event()
        return True

    # ---------- 退出 ----------
    def on_close(self):
        self.save_config()
        self.mouse_listener.stop()
        self.keyboard_listener.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not password_dialog():
        sys.exit(0)

    log_q = queue.Queue()
    sys.stdout = QueueWriter(log_q)
    sys.stderr = QueueWriter(log_q)

    # 解锁通过后才导入原主脚本（导入时它会创建/读取桌面上的编号文件）
    try:
        auto_mod = importlib.import_module(SCRIPT_MODULE)
    except Exception as e:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showerror("导入失败", f"无法导入原主脚本 {SCRIPT_MODULE}.py：\n{e}\n\n请检查 gui.py 顶部的 SCRIPT_MODULE。")
        sys.exit(1)

    App(auto_mod, log_q).run()