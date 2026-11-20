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

# Windows 键盘消息常量
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
LLKHF_INJECTED = 0x10       # 程序模拟的按键（如 pyautogui 发出的 ctrl+c），需要忽略
VK_TAB = 0x09

# 是否拦截滚轮（仅在标注页窗口内生效；True：滚轮不会再滚动页面/缩放波形）
SUPPRESS_WHEEL = True
# 滚轮冷却时间（秒）：滚一格会连续产生多个事件，冷却期内只触发一次
WHEEL_COOLDOWN = 0.8

# ====== 倍速配置 ======
SPEED_INPUT_POS = (1473, 305)   # 倍速输入框坐标（"倍速：1.00"中数字所在位置）
FAST_SPEED = "1.25"             # 第一次按 Tab 设置的倍速
NORMAL_SPEED = "1"              # 再按一次 Tab 恢复的倍速
# True：每次右键自动化后，把脚本记录的状态重置为"正常倍速"（适用于换题后页面倍速会回到 1 倍的情况）
# 如果换题后页面倍速保持不变，改成 False
RESET_SPEED_ON_NEW_PAGE = True

# ====== 静音柱贴合配置 ======
FIT_ENABLED = True
FIT_DRY_RUN = False           # True：只检测并打印，不拖动；确认打印结果正确后改成 False
# 波形区截图范围（屏幕坐标，已按你的完整截图实测：框 x≈442~1594，y≈171~251）
SCAN_X0, SCAN_Y0 = 380, 150
SCAN_W, SCAN_H = 1260, 125
BAR_MIN_HEIGHT = 30           # 静音柱竖线至少多少像素高（实测约 41）
MIN_COLUMN_PIXELS = 3         # 一列里波形像素不少于多少个，才算"有音频"（越小越灵敏）
FIT_TOLERANCE = 3             # 偏差不超过这个像素数就不拖
FIT_MAX_DRAG = 300            # 单次拖动超过这个像素数视为识别异常，不拖动
BAR_GAP = 2                   # 贴合后，静音柱与音频最边缘之间保留的像素

print("✅ 已设置触发键：鼠标右键 = 自动化，滚轮 = 重听音频，Tab = 1.25 / 1 倍速切换（仅在标注页窗口内生效）")
print("📄 编号保存位置：", OUTPUT_TXT)
print(f"📄 文件中已有 {len(saved_ids)} 条编号")

# 各任务独立的运行标志
auto_running = False
replay_running = False
speed_running = False
last_wheel_time = 0.0

# 当前是否处于 1.25 倍速（脚本记录，默认 False = 1 倍速）
speed_fast = False

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


# ====== 静音柱贴合：像素判断（颜色为实测值） ======
def _is_border(p):
    """框的青绿色边框（实测约 148,220,209）"""
    return p[1] >= 200 and p[1] - p[0] >= 50


def _is_bar(p):
    """静音柱竖线（亮度会随位置变化，实测 g 值在 168~218 之间）"""
    return p[1] >= 160 and p[1] - p[0] >= 55


def _is_wave(p):
    """波形像素（实测 g 最高约 153；播放头 54,154,160 因 r 值低被排除）"""
    return p[0] >= 65 and 110 <= p[1] < 160 and p[1] - p[0] >= 35


def analyze_wave(img):
    """
    分析波形区截图（坐标相对截图左上角），返回 (结果字典, 错误信息)。
    结果含：框的上下左右边缘、左右静音柱位置、音频左右端、左右各需拖动的像素 dx_l / dx_r
    """
    px = img.load()
    w, h = img.size

    # 1) 框的上下边框：青绿色像素很多的行
    rows = [r for r in range(h)
            if sum(1 for x in range(w) if _is_border(px[x, r])) >= 150]
    if not rows or max(rows) - min(rows) < 40:
        return None, "没找到框的上下边框"
    top, bottom = min(rows), max(rows)
    xs = [x for x in range(w) if _is_border(px[x, top])]
    fl, fr = min(xs), max(xs)          # 框左右边缘
    ya, yb = top + 4, bottom - 3       # 框内部扫描的行范围

    # 2) 左右静音柱：框内靠近左右边缘的亮色竖线
    def bar_cols(a, b):
        return [x for x in range(a, b)
                if sum(1 for y in range(ya, yb) if _is_bar(px[x, y])) >= BAR_MIN_HEIGHT]

    # 静音柱距框边缘实测 14~18 像素，只在 8~30 像素范围内找，避免把波形峰值误认成静音柱
    lb = bar_cols(fl + 8, fl + 30)
    rb = bar_cols(fr - 30, fr - 8)
    if not lb or not rb:
        return None, f"没找到静音柱（左={lb}，右={rb}）"
    bar_l, bar_r = min(lb), max(rb)   # 取离框边缘最近的那一列
    skip = {x + d for x in lb + rb for d in (-1, 0, 1)}   # 柱子及其抗锯齿边缘不参与音频判断

    # 3) 音频左右端：逐列统计波形像素（播放头、静音柱、中线都不会被算进去）
    audio_l = audio_r = None
    for x in range(fl + 4, fr - 3):
        if x in skip:
            continue
        cnt = sum(1 for y in range(ya, yb) if _is_wave(px[x, y]))
        if cnt >= MIN_COLUMN_PIXELS:
            if audio_l is None:
                audio_l = x
            audio_r = x
    if audio_l is None:
        return None, "没检测到音频波形"

    return {
        "top": top, "bottom": bottom, "fl": fl, "fr": fr,
        "bar_l": bar_l, "bar_r": bar_r,
        "audio_l": audio_l, "audio_r": audio_r,
        "dx_l": audio_l - (bar_l + BAR_GAP),   # 左静音柱需要右移（正）/ 左移（负）的像素
        "dx_r": audio_r - (bar_r - BAR_GAP),   # 右静音柱需要右移（正）/ 左移（负）的像素
    }, ""


def fit_silence_bars():
    """截图 -> 识别音频真实起止 -> 拖动框左右边缘，让静音柱贴合音频"""
    with mouse_lock:
        pyautogui.moveTo(1000, 600)   # 移开鼠标，避免悬停效果遮挡波形
        time.sleep(0.15)
        img = pyautogui.screenshot(region=(SCAN_X0, SCAN_Y0, SCAN_W, SCAN_H)).convert("RGB")

    res, err = analyze_wave(img)
    if res is None:
        print("⚠️ 静音柱贴合：", err)
        img.save(os.path.join(get_desktop_path(), "fit_debug.png"))
        return

    dx_l, dx_r = res["dx_l"], res["dx_r"]
    print(f"📏 框 {SCAN_X0 + res['fl']}~{SCAN_X0 + res['fr']}，"
          f"静音柱 {SCAN_X0 + res['bar_l']} / {SCAN_X0 + res['bar_r']}，"
          f"音频 {SCAN_X0 + res['audio_l']}~{SCAN_X0 + res['audio_r']}，"
          f"左需移动 {dx_l}px，右需移动 {dx_r}px")

    if FIT_DRY_RUN:
        return

    center_y = SCAN_Y0 + (res["top"] + res["bottom"]) // 2
    # 抓取点：框左边缘、右边缘（往框内偏 1 像素，避免点到框外）
    edges = ((SCAN_X0 + res["fl"] + 1, dx_l), (SCAN_X0 + res["fr"] - 1, dx_r))

    with mouse_lock:
        for edge_x, dx in edges:
            if abs(dx) <= FIT_TOLERANCE:
                continue
            if abs(dx) > FIT_MAX_DRAG:
                print(f"⚠️ 偏差 {dx}px 过大，疑似识别异常，已跳过")
                continue
            pyautogui.moveTo(edge_x, center_y)
            pyautogui.mouseDown()
            pyautogui.moveTo(edge_x + dx, center_y, duration=0.2)
            pyautogui.mouseUp()
            time.sleep(0.1)


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
    click(179, 256)             # 选中语句（同时重听音频）
    if FIT_ENABLED:
        try:
            fit_silence_bars()  # 选中语句后，再让静音柱贴合音频
        except Exception as e:
            print("⚠️ 静音柱贴合失败：", e)
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
    global auto_running, speed_fast
    try:
        extract_id()   # 先读取当前页编号，再执行原有点击流程
        cl()
        if RESET_SPEED_ON_NEW_PAGE:
            speed_fast = False
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


def toggle_speed():
    """在 1.25 和 1 倍速之间切换：点倍速输入框 -> 全选 -> 输入 -> 回车，完成后鼠标回到原位置"""
    global speed_running, speed_fast
    try:
        target = NORMAL_SPEED if speed_fast else FAST_SPEED
        with mouse_lock:
            x, y = pyautogui.position()
            pyautogui.click(SPEED_INPUT_POS[0], SPEED_INPUT_POS[1], button='left', duration=0.05)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.write(target, interval=0.03)
            pyautogui.press('enter')
            pyautogui.moveTo(x, y)
        speed_fast = not speed_fast
        print(f"⏩ 倍速已设置为 {target}")
    except Exception as e:
        print("⚠️ 调整倍速失败：", e)
    finally:
        speed_running = False


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


# 键盘事件过滤：只在标注页窗口内，Tab = 切换 1.25 / 1 倍速
def keyboard_event_filter(msg, data):
    global speed_running

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

    if msg == WM_KEYDOWN and not speed_running:
        speed_running = True
        print("检测到 Tab，切换倍速！")
        threading.Thread(target=toggle_speed, daemon=True).start()

    # 拦截 Tab，避免页面焦点跳动
    keyboard_listener.suppress_event()
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
    keyboard_listener = keyboard.Listener(
        on_release=on_release,
        win32_event_filter=keyboard_event_filter,
    )
    mouse_listener.start()
    keyboard_listener.start()
    print("监听已启动，右键执行自动化，滚轮重听音频，Tab 切换 1.25/1 倍速，ESC 退出监听")
    keyboard_listener.join()