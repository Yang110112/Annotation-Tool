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


def _reference_height(counts):
    """参考列高：所有"有声列"高度的百分位数，比直接取最大值稳定。"""
    active = sorted(v for v in counts.values() if v >= cfg.MIN_COLUMN_PIXELS)
    if not active:
        return 0
    pct = getattr(cfg, "EDGE_REF_PERCENTILE", 90)
    idx = min(len(active) - 1, int(len(active) * pct / 100))
    return active[idx]


def _noise_level(counts):
    """底噪高度：所有列高排序后取第 NOISE_PERCENTILE 百分位"""
    vals = sorted(counts.values())
    idx = int(len(vals) * cfg.NOISE_PERCENTILE / 100)
    return vals[min(idx, len(vals) - 1)]


def _find_edge_rise(counts, order, thr_low, thr_high, window):
    """
    找音频边缘：从 order 方向扫描，找第一个满足下面两条的位置：
    1) 从该列起连续 EDGE_MIN_RUN 列、列高都 >= thr_low；
    2) 从该列起 window 列之内，列高至少有一列 >= thr_high（连着强音）。
    孤立的底噪、细杂线达不到强音，会被跳过。找不到返回 None。
    """
    n = len(order)
    for i in range(n):
        if counts[order[i]] < thr_low:
            continue
        seg = order[i:i + cfg.EDGE_MIN_RUN]
        if len(seg) < cfg.EDGE_MIN_RUN or any(counts[x] < thr_low for x in seg):
            continue
        if max(counts[x] for x in order[i:i + window]) >= thr_high:
            return order[i]
    return None


def analyze_wave(img):
    """
    分析波形区截图（坐标相对截图左上角），返回 (结果字典, 错误信息)。
    音频边缘：连续 EDGE_MIN_RUN 列 >= 低阈值，且边缘往里 EDGE_RISE_WINDOW 列内出现强音。
    """
    px = img.load()
    w, h = img.size

    # 1) 框的上下边框
    rows = [r for r in range(h)
            if sum(1 for x in range(w) if _is_border(px[x, r])) >= 150]
    if not rows or max(rows) - min(rows) < 40:
        return None, "没找到框的上下边框"
    top, bottom = min(rows), max(rows)
    xs = [x for x in range(w) if _is_border(px[x, top])]
    fl, fr = min(xs), max(xs)
    ya, yb = top + 4, bottom - 3

    # 2) 左右静音柱
    def bar_cols(a, b):
        return [x for x in range(a, b)
                if sum(1 for y in range(ya, yb) if _is_bar(px[x, y])) >= cfg.BAR_MIN_HEIGHT]

    lb = bar_cols(fl + 8, fl + 30)
    rb = bar_cols(fr - 30, fr - 8)
    if not lb or not rb:
        return None, f"没找到静音柱（左={lb}，右={rb}）"
    bar_l, bar_r = min(lb), max(rb)
    skip = {x + d for x in lb + rb for d in (-1, 0, 1)}

    # 3) 逐列统计波形像素
    cols = list(range(fl + 4, fr - 3))
    counts = {x: 0 if x in skip else sum(1 for y in range(ya, yb) if _is_wave(px[x, y]))
              for x in cols}
    peak = max(counts.values())
    if peak < cfg.MIN_COLUMN_PIXELS:
        return None, "没检测到音频波形"

    # 4) 低阈值找候选边缘，边缘附近必须连着强音
    ref = _reference_height(counts)
    noise = _noise_level(counts)
    thr_low = max(cfg.MIN_COLUMN_PIXELS, noise * cfg.NOISE_MULT, ref * cfg.EDGE_LOW_RATIO)
    thr_high = max(thr_low + 1, ref * cfg.EDGE_HIGH_RATIO)
    thr_l = thr_r = thr_low
    audio_l = _find_edge_rise(counts, cols, thr_low, thr_high, cfg.EDGE_RISE_WINDOW)
    audio_r = _find_edge_rise(counts, cols[::-1], thr_low, thr_high, cfg.EDGE_RISE_WINDOW)
    if audio_l is None or audio_r is None or audio_l >= audio_r:
        return None, f"没找到有效音频边缘（最大列高={peak}，参考列高={ref}，底噪={noise}）"

    return {
        "top": top, "bottom": bottom, "fl": fl, "fr": fr,
        "bar_l": bar_l, "bar_r": bar_r,
        "audio_l": audio_l, "audio_r": audio_r,
        "peak": peak, "ref": ref, "noise": noise,
        "thr_l": thr_l, "thr_r": thr_r, "thr_high": thr_high,
        "dx_l": audio_l - (bar_l + cfg.BAR_GAP),
        "dx_r": audio_r - (bar_r - cfg.BAR_GAP),
    }, ""


def _measure():
    """移开鼠标 -> 截图 -> 分析，返回 (结果, 截图, 错误信息)"""
    with state.mouse_lock:
        pyautogui.moveTo(1000, 600)   # 移开鼠标，避免悬停效果遮挡波形
        time.sleep(0.15)
        img = pyautogui.screenshot(
            region=(cfg.SCAN_X0, cfg.SCAN_Y0, cfg.SCAN_W, cfg.SCAN_H)).convert("RGB")
    res, err = analyze_wave(img)
    return res, img, err


def fit_silence_bars():
    """识别音频真实起止 -> 拖动 -> 重新测量，直到左右静音柱都贴合音频"""
    x0, y0 = cfg.SCAN_X0, cfg.SCAN_Y0

    for rnd in range(1, cfg.FIT_MAX_ROUNDS + 1):
        res, img, err = _measure()
        if res is None:
            print("⚠️ 静音柱贴合：", err)
            img.save(os.path.join(get_desktop_path(), "fit_debug.png"))
            return

        dx_l, dx_r = res["dx_l"], res["dx_r"]
        print(f"📏 第{rnd}轮 框 {x0 + res['fl']}~{x0 + res['fr']}，"
              f"静音柱 {x0 + res['bar_l']} / {x0 + res['bar_r']}，"
              f"音频 {x0 + res['audio_l']}~{x0 + res['audio_r']}，"
              f"最大列高 {res['peak']}，参考列高 {res['ref']}，底噪 {res['noise']}，"
              f"低阈值 {res['thr_l']:.1f}，强音阈值 {res['thr_high']:.1f}，"
              f"左柱需移动 {dx_l}px，右柱需移动 {dx_r}px")

        if abs(dx_l) <= cfg.FIT_TOLERANCE and abs(dx_r) <= cfg.FIT_TOLERANCE:
            print("✅ 静音柱已贴合音频")
            return
        if cfg.FIT_DRY_RUN:
            return

        center_y = y0 + (res["top"] + res["bottom"]) // 2
        if cfg.FIT_GRAB == "bar":
            grabs = ((x0 + res["bar_l"], dx_l), (x0 + res["bar_r"], dx_r))
        else:
            grabs = ((x0 + res["fl"] + 1, dx_l), (x0 + res["fr"] - 1, dx_r))

        with state.mouse_lock:
            for grab_x, dx in grabs:
                if abs(dx) <= cfg.FIT_TOLERANCE:
                    continue
                if abs(dx) > cfg.FIT_MAX_DRAG:
                    print(f"⚠️ 偏差 {dx}px 过大，疑似识别异常，已跳过")
                    continue
                pyautogui.moveTo(grab_x, center_y)
                pyautogui.mouseDown()
                pyautogui.moveTo(grab_x + dx, center_y, duration=0.2)
                pyautogui.mouseUp()
                time.sleep(0.1)

    print("⚠️ 静音柱贴合：达到最大轮数仍有偏差，请查看日志，必要时把 FIT_GRAB 改成 \"bar\"")