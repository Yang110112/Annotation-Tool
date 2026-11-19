import ctypes
import os
import re
import threading
from mima import unlock
import pyautogui
import pyperclip
import time
from pynput import keyboard, mouse

# 获取屏幕尺寸
screen_size = pyautogui.size()
print("屏幕大小：", screen_size)

# 只有当前窗口标题包含下面任意一个关键词时，快捷键才生效
# 标注页标题示例："赣州-区域3-单人转写标注-汇智 标注任务 - Microsoft Edge"
TARGET_KEYWORDS = ["单人转写标注"]
# True：每次触发都会打印当前窗口标题，方便确认关键词是否写对
DEBUG_TITLE = True


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


# ====== 编号提取配置 ======
ID_POS = (172, 1014)        # 页面底部"编号：xxxxx"中数字的坐标，双击选中
from datetime import datetime
_today = datetime.now()   # 读取系统当前日期
OUTPUT_TXT = os.path.join(get_desktop_path(), f"标注编号{_today.month}.{_today.day}.txt")    # 每行一个编号，按日期命名

# 启动时自动创建文件（已存在则保留原内容），并读取已有编号用于去重
os.makedirs(os.path.dirname(OUTPUT_TXT), exist_ok=True)
with open(OUTPUT_TXT, "a", encoding="utf-8"):
    pass
with open(OUTPUT_TXT, "r", encoding="utf-8") as _f:
    saved_ids = {line.strip() for line in _f if line.strip()}

# Windows 鼠标消息常量
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A

# 是否拦截滚轮（仅在标注页窗口内生效；True：滚轮不会再滚动页面/缩放波形）
SUPPRESS_WHEEL = True
# 滚轮冷却时间（秒）：滚一格会连续产生多个事件，冷却期内只触发一次
WHEEL_COOLDOWN = 0.8

print("✅ 已设置触发键：鼠标右键 = 自动化，滚轮 = 重听音频（仅在标注页窗口内生效）")
print("📄 编号保存位置：", OUTPUT_TXT)
print(f"📄 文件中已有 {len(saved_ids)} 条编号")

# 两个任务各自独立的运行标志
auto_running = False
replay_running = False
last_wheel_time = 0.0

# 鼠标操作锁：同一时刻只允许一个任务操作鼠标
mouse_lock = threading.RLock()

record_count = len(saved_ids)


def get_foreground_title():
    """获取当前最前面窗口的标题"""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def in_target_window(show=False):
    """当前窗口是否是标注页"""
    title = get_foreground_title()
    if show and DEBUG_TITLE:
        print("当前窗口标题：", title)
    return any(k in title for k in TARGET_KEYWORDS)


def extract_id():
    """双击选中页面底部的编号 -> 复制 -> 读剪贴板 -> 追加写入 txt"""
    global record_count
    try:
        with mouse_lock:
            pyperclip.copy("")  # 先清空剪贴板，避免读到上一次的旧内容
            pyautogui.doubleClick(ID_POS[0], ID_POS[1])
            time.sleep(0.15)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.15)
            raw = pyperclip.paste()

        m = re.search(r"\d+", raw or "")
        if not m:
            print(f"⚠️ 没读到编号，剪贴板内容：{raw!r}")
            return
        num = m.group()

        # 编号已记录过（同一页重复触发，或重启脚本后重复）则不重复写入
        if num in saved_ids:
            print(f"⚠️ 编号 {num} 已记录过，跳过")
            return
        saved_ids.add(num)
        record_count += 1
        with open(OUTPUT_TXT, "a", encoding="utf-8") as f:
            f.write(num + "\n")
        print(f"📝 已保存第 {record_count} 条：{num}")
    except Exception as e:
        print("⚠️ 提取编号失败：", e)


def click(x, y):
    """加锁点击：保证重听可以插在两次点击之间，而不是打断一次点击"""
    with mouse_lock:
        pyautogui.click(x, y, button='left', duration=0.1)


def cl():
    time.sleep(0.2)
    click(179, 256)
    click(393, 470)
    click(393, 567)
    click(524, 658)
    click(524, 750)
    click(524, 840)
    click(1845, 724)
    click(1777, 953)

    # 复制 -> 点转写框 -> 粘贴 这一段必须连续完成，整体加锁，避免被重听打断
    with mouse_lock:
        # ctrl+a 全选
        pyautogui.hotkey('ctrl', 'a')
        # ctrl+c 复制
        pyautogui.hotkey('ctrl', 'c')

        pyautogui.click(651, 943, button='left', duration=0.1)
        # ctrl+a
        pyautogui.hotkey('ctrl', 'a')
        # ctrl+v 粘贴
        pyautogui.hotkey('ctrl', 'v')
        pyautogui.moveTo(1717, 1017, duration=0.2)
        # pyautogui.click(1713, 1015, button='left', duration=0.1)

    # 这 5 秒在锁外面，期间滚动滚轮可以立即重听
    time.sleep(5)


def run_task():
    global auto_running
    try:
        extract_id()   # 先读取当前页编号，再执行原有点击流程
        cl()
    finally:
        auto_running = False


def replay_audio():
    """重听音频：点击 (179, 256)，点完后鼠标回到原位置"""
    global replay_running
    try:
        with mouse_lock:
            x, y = pyautogui.position()
            pyautogui.click(179, 256, button='left', duration=0.1)
            pyautogui.moveTo(x, y)
    finally:
        replay_running = False


# 鼠标事件过滤：只在标注页窗口内，右键 = 自动化，滚轮 = 重听，并拦截对应事件
def win32_event_filter(msg, data):
    global auto_running, replay_running, last_wheel_time

    if msg in (WM_RBUTTONDOWN, WM_RBUTTONUP):
        # 不在标注页：直接放行，右键菜单等功能完全正常
        if not in_target_window(show=(msg == WM_RBUTTONDOWN)):
            return True
        if msg == WM_RBUTTONDOWN and not auto_running:
            auto_running = True
            print("检测到鼠标右键，开始执行自动化！")
            # 放到新线程执行，避免阻塞鼠标钩子
            threading.Thread(target=run_task, daemon=True).start()
        mouse_listener.suppress_event()

    elif msg == WM_MOUSEWHEEL:
        # 不在标注页：直接放行，其他程序里滚轮正常滚动
        if not in_target_window():
            return True
        now = time.time()
        if not replay_running and now - last_wheel_time > WHEEL_COOLDOWN:
            last_wheel_time = now
            replay_running = True
            print("检测到滚轮滚动，重听音频！")
            threading.Thread(target=replay_audio, daemon=True).start()
        if SUPPRESS_WHEEL:
            mouse_listener.suppress_event()

    return True


def on_release(key):
    # 按esc停止监听
    if key == keyboard.Key.esc:
        print("停止监听")
        mouse_listener.stop()
        return False


if __name__ == "__main__":
    if not unlock():
        exit()

    mouse_listener = mouse.Listener(win32_event_filter=win32_event_filter)
    keyboard_listener = keyboard.Listener(on_release=on_release)
    mouse_listener.start()
    keyboard_listener.start()
    print("监听已启动，右键执行自动化，滚轮重听音频，ESC 退出监听")
    keyboard_listener.join()