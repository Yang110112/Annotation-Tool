# -*- coding: utf-8 -*-
"""
gui.py —— 标注自动化助手（可视化界面）
运行方式：python gui.py
"""
import queue
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

import actions
import config
import mima
from hotkeys import HotkeyManager
from settings import ACTIONS, DEFAULT_BINDINGS, DEFAULT_MILESTONE, load_settings, save_settings

FONT = ("Microsoft YaHei UI", 10)

# 界面上每个功能的显示文字
ACTION_ROWS = (
    ("auto", "自动化（提取编号 + 点击 + 粘贴）"),
    ("replay", "重听音频"),
    ("speed", "倍速切换（1.25 / 1 倍速）"),
)
# 日志里用的短名称
ACTION_NAMES = {"auto": "自动化", "replay": "重听音频", "speed": "倍速切换"}

# 功能开关（key 对应 actions.features）
FEATURE_ROWS = (
    ("fit", "拉音频（让静音柱贴合音频）"),
    ("paste", "复制粘贴文本（复制语句 → 粘贴到转写框）"),
    ("write_id", "将编号写入文本文件（标注编号月.日.txt）"),
)
FEATURE_NAMES = {"fit": "拉音频", "paste": "复制粘贴文本", "write_id": "编号写入文本"}

# 每满 100 条的完成提示窗：显示多少秒后自动消失（点一下也可立即关闭）
POPUP_SECONDS = 3


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
        if mima.check_password(entry.get()):
            mima.mark_unlocked()
            result["ok"] = True
            messagebox.showinfo("解锁成功", "✅ 解锁成功！以后启动不再需要输入密码")
            root.destroy()
            return
        result["tries"] += 1
        left = mima.MAX_RETRY - result["tries"]
        if left <= 0:
            messagebox.showerror("解锁失败", "⛔ 次数用尽，解锁失败，即将关机！")
            root.destroy()
            mima.shutdown1234()
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
    def __init__(self, log_q):
        self.q = log_q                # 日志 + 事件队列
        settings = load_settings(config.TARGET_KEYWORDS)
        self.keywords_init = settings["keywords"]
        self.hk = HotkeyManager(log_q, settings["bindings"], settings["suppress"])
        # 完成条数回调在工作线程里触发，只往队列放消息，弹窗由界面线程处理
        actions.on_milestone = lambda n: self.q.put(("milestone", n))
        actions.MILESTONE_EVERY = settings["milestone"]     # 每多少条弹一次窗（界面可改）

        self.root = tk.Tk()
        self.root.title("标注自动化助手")
        self.root.geometry("680x770")
        self.build_ui()

        config.TARGET_KEYWORDS = self.parse_keywords()
        self.hk.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---------- 配置 ----------
    def save_config(self):
        save_settings(self.hk.bindings, self.parse_keywords(), self.hk.suppress,
                      milestone=actions.MILESTONE_EVERY)

    # ---------- 界面 ----------
    def build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        self.status_var = tk.StringVar()
        self.status_lbl = tk.Label(main, textvariable=self.status_var,
                                   font=("Microsoft YaHei UI", 11, "bold"), anchor="w")
        self.status_lbl.pack(fill="x")

        box = ttk.LabelFrame(main, text="触发按键（点“设置按键”后，按下想用的键盘键 / 鼠标键 / 滚轮）", padding=10)
        box.pack(fill="x", pady=10)
        self.bind_vars, self.bind_btns = {}, {}
        for i, (action, title) in enumerate(ACTION_ROWS):
            ttk.Label(box, text=title, font=FONT, width=28).grid(row=i, column=0, sticky="w", pady=6)
            var = tk.StringVar()
            ttk.Label(box, textvariable=var, font=FONT, width=24, relief="groove",
                      anchor="center").grid(row=i, column=1, padx=8)
            btn = ttk.Button(box, text="设置按键", command=lambda a=action: self.start_record(a))
            btn.grid(row=i, column=2)
            self.bind_vars[action], self.bind_btns[action] = var, btn
        ttk.Label(box, text="提示：Esc 可取消录入；监听中按 Esc 会暂停监听\n"
                            "录入时按 Ctrl 会记为“Ctrl（单按）”：按下松开、期间没按其他键才触发",
                  foreground="gray", justify="left").grid(
            row=len(ACTION_ROWS), column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.refresh_binding_text()

        feat = ttk.LabelFrame(main, text="功能开关（默认全部开启，可手动关闭；每次启动都会恢复开启）", padding=10)
        feat.pack(fill="x", pady=(0, 10))
        self.feature_vars = {}
        for key, text in FEATURE_ROWS:
            var = tk.BooleanVar(value=actions.features[key])
            var.trace_add("write", lambda *a, k=key, v=var: self.on_feature_toggle(k, v.get()))
            ttk.Checkbutton(feat, text=text, variable=var).pack(anchor="w", pady=2)
            self.feature_vars[key] = var

        opt = ttk.LabelFrame(main, text="其他设置", padding=10)
        opt.pack(fill="x")
        ttk.Label(opt, text="目标窗口标题关键词（多个用逗号分隔）：", font=FONT).grid(row=0, column=0, sticky="w")
        self.kw_var = tk.StringVar(value="，".join(self.keywords_init))
        ttk.Entry(opt, textvariable=self.kw_var, width=34, font=FONT).grid(row=0, column=1, padx=8, sticky="w")
        self.suppress_var = tk.BooleanVar(value=self.hk.suppress)
        self.suppress_var.trace_add("write", lambda *a: setattr(self.hk, "suppress", self.suppress_var.get()))
        ttk.Checkbutton(opt, text="在标注页内拦截触发键（不再传给页面，和原脚本行为一致）",
                        variable=self.suppress_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        mf = ttk.Frame(opt)
        mf.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(mf, text="每完成", font=FONT).pack(side="left")
        self.milestone_var = tk.StringVar(value=str(actions.MILESTONE_EVERY))
        self.milestone_var.trace_add("write", lambda *a: self.apply_milestone())
        ent = ttk.Entry(mf, textvariable=self.milestone_var, width=7, font=FONT, justify="center")
        ent.pack(side="left", padx=6)
        # 输入框失去焦点时，如果内容无效，就恢复成当前生效的条数
        ent.bind("<FocusOut>", lambda e: self.milestone_var.set(str(actions.MILESTONE_EVERY)))
        ttk.Label(mf, text=f"条弹窗提醒一次（默认 {DEFAULT_MILESTONE}，输入 1~99999 的整数）", font=FONT).pack(side="left")

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

    def refresh_binding_text(self):
        for action in ACTIONS:
            self.bind_vars[action].set(HotkeyManager.describe(self.hk.bindings.get(action)))

    def update_status(self):
        if self.hk.recording:
            self.status_var.set("● 请按下想要的按键…（Esc 取消）")
            self.status_lbl.config(fg="#d97706")
        elif self.hk.enabled:
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

    # ---------- 功能开关 ----------
    def on_feature_toggle(self, key, value):
        actions.set_feature(key, value)
        print(f"功能开关：{FEATURE_NAMES[key]} 已{'开启' if value else '关闭'}")

    def apply_milestone(self):
        """输入框内容是 1~99999 的整数时立即生效；其他内容（比如正在输入、空白）先忽略"""
        raw = self.milestone_var.get().strip()
        if raw.isdigit() and 1 <= int(raw) <= 99999:
            actions.MILESTONE_EVERY = int(raw)

    # ---------- 按钮动作 ----------
    def parse_keywords(self):
        raw = self.kw_var.get().replace("，", ",")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def toggle(self):
        if self.hk.recording:
            return
        if not self.hk.enabled:
            kws = self.parse_keywords()
            if not kws:
                messagebox.showwarning("提示", "目标窗口关键词不能为空，否则任何窗口都不会触发。")
                return
            config.TARGET_KEYWORDS = kws
            self.save_config()
        self.set_enabled(not self.hk.enabled)

    def set_enabled(self, value):
        self.hk.enabled = value
        self.hk.held.clear()
        self.toggle_btn.config(text="■ 暂停监听" if value else "▶ 开始监听")
        self.update_status()
        print("监听已启动" if value else "监听已暂停")

    def reset_default(self):
        if self.hk.recording:
            return
        self.hk.bindings = {a: dict(b) for a, b in DEFAULT_BINDINGS.items()}
        self.refresh_binding_text()
        self.save_config()

    def start_record(self, action):
        if self.hk.recording:
            return
        self.hk.held.clear()
        self.hk.recording = action
        for b in self.bind_btns.values():
            b.config(state="disabled")
        self.toggle_btn.config(state="disabled")
        self.update_status()

    def end_record_ui(self):
        for b in self.bind_btns.values():
            b.config(state="normal")
        self.toggle_btn.config(state="normal")
        self.update_status()

    def on_recorded(self, action, b):
        self.end_record_ui()
        # 与其他所有功能比对冲突（现在有三个功能，不能只比对一个）
        for other in ACTIONS:
            if other != action and HotkeyManager.conflict(b, self.hk.bindings.get(other)):
                messagebox.showwarning(
                    "按键冲突", f"这个按键已被“{ACTION_NAMES[other]}”使用，请换一个。")
                return
        if b["type"] == "mouse" and b["code"] == "left" and self.hk.suppress:
            if not messagebox.askyesno(
                    "确认",
                    "你选了鼠标左键，并且开启了“拦截触发键”。\n"
                    "这样在标注页里左键将无法正常点击页面。\n\n仍要使用吗？"):
                return
        self.hk.bindings[action] = b
        self.refresh_binding_text()
        self.save_config()
        print(f"已设置：{ACTION_NAMES[action]} = {HotkeyManager.describe(b)}")

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
                    self.end_record_ui()
                elif kind == "milestone":
                    try:
                        self.show_milestone(item[1])
                    except Exception:
                        import traceback
                        self.append_log("⚠️ 弹窗失败：\n" + traceback.format_exc())
                elif kind == "stop":
                    self.set_enabled(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---------- 每满 100 条的完成提示窗 ----------
    def show_milestone(self, n):
        """完成提示窗：置顶 + 不抢焦点 + 鼠标穿透 + 不进任务栏，不影响标注页的任何操作，几秒后自动消失"""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")   # 独立实例，不改动其他模块用的 ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]

        prev = user32.GetForegroundWindow()    # 记住弹窗出现前的前台窗口（标注页）

        pop = tk.Toplevel(self.root)
        pop.withdraw()
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        pop.attributes("-alpha", 0.96)
        # 红色醒目弹窗。红色不在 fit_bars 的识别颜色范围内（边框/静音柱是青绿色，波形 g 值 110~160），
        # 且位于屏幕右上角、波形框的右侧，不会遮住波形框，所以不影响静音柱贴合
        bg = "#dc2626"
        pop.configure(bg=bg)
        tk.Label(pop, text=f"✔ 已完成 {n} 条", font=("Microsoft YaHei UI", 30, "bold"),
                 fg="white", bg=bg, padx=44, pady=20).pack()
        tk.Label(pop, text=f"{POPUP_SECONDS} 秒后自动消失", font=("Microsoft YaHei UI", 11),
                 fg="white", bg=bg, pady=8).pack()

        pop.update_idletasks()
        w = pop.winfo_reqwidth()
        pop.geometry(f"+{pop.winfo_screenwidth() - w - 20}+20")   # 屏幕右上角

        def apply_style():
            # 0x08000000 不激活(NOACTIVATE) | 0x80 工具窗口(不进任务栏) | 0x80000 分层 | 0x20 鼠标穿透
            try:
                hwnd = user32.GetParent(pop.winfo_id()) or pop.winfo_id()
                style = user32.GetWindowLongW(hwnd, -20)
                user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080 | 0x00080000 | 0x00000020)
            except Exception as e:
                print("⚠️ 设置弹窗样式失败：", e)

        apply_style()
        pop.deiconify()
        apply_style()                          # 显示后再设一次，防止被 Tk 覆盖
        pop.lift()

        # 保险：如果前台窗口被抢走了，立刻还给原来的窗口
        try:
            if prev and user32.GetForegroundWindow() != prev:
                user32.SetForegroundWindow(prev)
        except Exception:
            pass

        def close():
            try:
                pop.destroy()
            except tk.TclError:
                pass

        pop.after(POPUP_SECONDS * 1000, close)

    # ---------- 退出 ----------
    def on_close(self):
        self.save_config()
        self.hk.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not password_dialog():
        sys.exit(0)

    log_q = queue.Queue()
    sys.stdout = QueueWriter(log_q)
    sys.stderr = QueueWriter(log_q)

    # 解锁通过后才初始化（会创建/读取桌面上的编号文件）
    try:
        actions.init()
    except Exception as e:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showerror("初始化失败", f"{e}")
        sys.exit(1)

    App(log_q).run()