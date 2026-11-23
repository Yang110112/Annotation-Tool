# -*- coding: utf-8 -*-
"""actions.py —— 三个核心动作（自动化 / 重听 / 倍速）及其触发入口"""
import threading
import time

import pyautogui

import config as cfg
from fit_bars import fit_silence_bars
from id_store import store
from state import state

# ====== 完成计数：每读到一个新编号算 1 条，每满 MILESTONE_EVERY 条提醒一次 ======
MILESTONE_EVERY = 100   # 默认值；GUI 版会用界面里输入的条数覆盖它
done_count = 0          # 本次运行已完成的条数（重启程序后从 0 重新数）
on_milestone = None     # GUI 会把它设成回调函数：on_milestone(已完成条数)

# ====== 功能开关（界面上可手动关闭，默认全部开启；每次启动都恢复开启）======
features = {
    "fit": True,        # 拉音频：让静音柱贴合音频
    "paste": True,      # 复制粘贴文本：复制语句 -> 点转写框 -> 粘贴
    "write_id": True,   # 把编号写入文本文件
}


def set_feature(name, value):
    features[name] = bool(value)
    if name == "write_id":
        store.write_enabled = bool(value)


def count_done():
    """读到新编号后调用：计数 +1，满 MILESTONE_EVERY 条时通知界面弹窗"""
    global done_count
    done_count += 1
    if done_count % MILESTONE_EVERY == 0:
        print(f"🎉 已完成 {done_count} 条")
        if on_milestone:
            try:
                on_milestone(done_count)
            except Exception as e:
                print("⚠️ 弹窗通知失败：", e)


def init():
    """启动时调用一次：打印屏幕信息，创建/读取编号文件"""
    print("屏幕大小：", pyautogui.size())
    store.load()
    print("📄 编号保存位置：", store.path)
    print(f"📄 文件中已有 {len(store.saved_ids)} 条编号")


def click(x, y):
    """加锁点击：保证重听可以插在两次点击之间，而不是打断一次点击"""
    with state.mouse_lock:
        pyautogui.click(x, y, button='left', duration=0.1)


def cl():
    time.sleep(0.2)
    click(*cfg.REPLAY_POS)          # 选中语句（同时重听音频）
    if features["fit"]:
        try:
            fit_silence_bars()      # 选中语句后，再让静音柱贴合音频
        except Exception as e:
            print("⚠️ 静音柱贴合失败：", e)
    for pos in cfg.CLICK_SEQUENCE:
        click(*pos)

    # 复制 -> 点转写框 -> 粘贴 这一段必须连续完成，整体加锁，避免被重听打断
    with state.mouse_lock:
        if features["paste"]:
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.hotkey('ctrl', 'c')

            pyautogui.click(cfg.TRANSCRIBE_BOX_POS[0], cfg.TRANSCRIBE_BOX_POS[1],
                            button='left', duration=0.1)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.hotkey('ctrl', 'v')
        pyautogui.moveTo(cfg.PARK_POS[0], cfg.PARK_POS[1], duration=0.2)

    # 这几秒在锁外面，期间滚动滚轮可以立即重听
    time.sleep(cfg.AFTER_TASK_WAIT)


def run_task():
    try:
        is_new = store.extract()   # 先读取当前页编号（True = 新编号，False = 重复/没读到）
        if is_new:
            count_done()           # 读到新编号就立刻计数，满 100 条马上弹窗，不等后面的点击流程
        else:
            print("↩️ 该编号重复或未读到，不计入完成条数")
        cl()                       # 再执行点击 / 粘贴流程
        if cfg.RESET_SPEED_ON_NEW_PAGE:
            state.speed_fast = False
    finally:
        state.auto_running = False


def replay_audio():
    """重听音频：点击一下，点完后鼠标回到原位置"""
    try:
        with state.mouse_lock:
            x, y = pyautogui.position()
            pyautogui.click(cfg.REPLAY_POS[0], cfg.REPLAY_POS[1], button='left', duration=0.1)
            pyautogui.moveTo(x, y)
    finally:
        state.replay_running = False


def toggle_speed():
    """在 1.25 和 1 倍速之间切换：点倍速输入框 -> 全选 -> 输入 -> 回车，完成后鼠标回到原位置"""
    try:
        target = cfg.NORMAL_SPEED if state.speed_fast else cfg.FAST_SPEED
        with state.mouse_lock:
            x, y = pyautogui.position()
            pyautogui.click(cfg.SPEED_INPUT_POS[0], cfg.SPEED_INPUT_POS[1],
                            button='left', duration=0.05)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.write(target, interval=0.03)
            pyautogui.press('enter')
            pyautogui.moveTo(x, y)
        state.speed_fast = not state.speed_fast
        print(f"⏩ 倍速已设置为 {target}")
    except Exception as e:
        print("⚠️ 调整倍速失败：", e)
    finally:
        state.speed_running = False


# ====== 触发入口（命令行版和 GUI 版共用）======
# 放到新线程执行，避免阻塞鼠标/键盘钩子
def start_auto(desc="触发键"):
    if state.auto_running:
        return
    state.auto_running = True
    print(f"检测到{desc}，开始执行自动化！")
    threading.Thread(target=run_task, daemon=True).start()


def start_replay(desc="触发键", is_wheel=False):
    if state.replay_running:
        return
    if is_wheel:
        now = time.time()
        if now - state.last_wheel_time <= cfg.WHEEL_COOLDOWN:
            return
        state.last_wheel_time = now
    state.replay_running = True
    print(f"检测到{desc}，重听音频！")
    threading.Thread(target=replay_audio, daemon=True).start()


def start_speed(desc="Tab"):
    if state.speed_running:
        return
    state.speed_running = True
    print(f"检测到{desc}，切换倍速！")
    threading.Thread(target=toggle_speed, daemon=True).start()