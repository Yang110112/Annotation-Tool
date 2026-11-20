# -*- coding: utf-8 -*-
"""fit_bars.py —— 静音柱识别与贴合"""
import os
import time

import pyautogui

import config as cfg
from state import state
from winutil import get_desktop_path


# ====== 像素判断（颜色为实测值） ======
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
                if sum(1 for y in range(ya, yb) if _is_bar(px[x, y])) >= cfg.BAR_MIN_HEIGHT]

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
        if cnt >= cfg.MIN_COLUMN_PIXELS:
            if audio_l is None:
                audio_l = x
            audio_r = x
    if audio_l is None:
        return None, "没检测到音频波形"

    return {
        "top": top, "bottom": bottom, "fl": fl, "fr": fr,
        "bar_l": bar_l, "bar_r": bar_r,
        "audio_l": audio_l, "audio_r": audio_r,
        "dx_l": audio_l - (bar_l + cfg.BAR_GAP),   # 左静音柱需要右移（正）/ 左移（负）的像素
        "dx_r": audio_r - (bar_r - cfg.BAR_GAP),   # 右静音柱需要右移（正）/ 左移（负）的像素
    }, ""


def fit_silence_bars():
    """截图 -> 识别音频真实起止 -> 拖动框左右边缘，让静音柱贴合音频"""
    x0, y0 = cfg.SCAN_X0, cfg.SCAN_Y0
    with state.mouse_lock:
        pyautogui.moveTo(1000, 600)   # 移开鼠标，避免悬停效果遮挡波形
        time.sleep(0.15)
        img = pyautogui.screenshot(region=(x0, y0, cfg.SCAN_W, cfg.SCAN_H)).convert("RGB")

    res, err = analyze_wave(img)
    if res is None:
        print("⚠️ 静音柱贴合：", err)
        img.save(os.path.join(get_desktop_path(), "fit_debug.png"))
        return

    dx_l, dx_r = res["dx_l"], res["dx_r"]
    print(f"📏 框 {x0 + res['fl']}~{x0 + res['fr']}，"
          f"静音柱 {x0 + res['bar_l']} / {x0 + res['bar_r']}，"
          f"音频 {x0 + res['audio_l']}~{x0 + res['audio_r']}，"
          f"左需移动 {dx_l}px，右需移动 {dx_r}px")

    if cfg.FIT_DRY_RUN:
        return

    center_y = y0 + (res["top"] + res["bottom"]) // 2
    # 抓取点：框左边缘、右边缘（往框内偏 1 像素，避免点到框外）
    edges = ((x0 + res["fl"] + 1, dx_l), (x0 + res["fr"] - 1, dx_r))

    with state.mouse_lock:
        for edge_x, dx in edges:
            if abs(dx) <= cfg.FIT_TOLERANCE:
                continue
            if abs(dx) > cfg.FIT_MAX_DRAG:
                print(f"⚠️ 偏差 {dx}px 过大，疑似识别异常，已跳过")
                continue
            pyautogui.moveTo(edge_x, center_y)
            pyautogui.mouseDown()
            pyautogui.moveTo(edge_x + dx, center_y, duration=0.2)
            pyautogui.mouseUp()
            time.sleep(0.1)