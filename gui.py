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
from settings import DEFAULT_BINDINGS, load_settings, save_settings

FONT = ("Microsoft YaHei UI", 10)


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

        self.root = tk.Tk()
        self.root.title("标注自动化助手")
        self.root.geometry("680x600")
        self.build_ui()

        config.TARGET_KEYWORDS = self.parse_keywords()
        self.hk.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---------- 配置 ----------
    def save_config(self):
        save_settings(self.hk.bindings, self.parse_keywords(), self.hk.suppress)

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
        rows = (("auto", "自动化（提取编号 + 点击 + 粘贴）"), ("replay", "重听音频"))
        for i, (action, title) in enumerate(rows):
            ttk.Label(box, text=title, font=FONT, width=28).grid(row=i, column=0, sticky="w", pady=6)
            var = tk.StringVar()
            ttk.Label(box, textvariable=var, font=FONT, width=24, relief="groove",
                      anchor="center").grid(row=i, column=1, padx=8)
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
        self.suppress_var = tk.BooleanVar(value=self.hk.suppress)
        self.suppress_var.trace_add("write", lambda *a: setattr(self.hk, "suppress", self.suppress_var.get()))
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

    def refresh_binding_text(self):
        for action in ("auto", "replay"):
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
        self.hk.bindings = dict(DEFAULT_BINDINGS)
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
        other = "replay" if action == "auto" else "auto"
        if HotkeyManager.conflict(b, self.hk.bindings.get(other)):
            messagebox.showwarning("按键冲突", "这个按键已被另一个功能使用，请换一个。")
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
        print(f"已设置：{'自动化' if action == 'auto' else '重听音频'} = {HotkeyManager.describe(b)}")

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
                elif kind == "stop":
                    self.set_enabled(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

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