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
    """
    参考列高：所有"有声列"（列高 >= MIN_COLUMN_PIXELS）的高度，取百分位数。
    比直接取最大值稳定，单个尖峰不会把阈值拉高。
    """
    active = sorted(v for v in counts.values() if v >= cfg.MIN_COLUMN_PIXELS)
    if not active:
        return 0
    pct = getattr(cfg, "EDGE_REF_PERCENTILE", 90)
    idx = min(len(active) - 1, int(len(active) * pct / 100))
    return active[idx]


def _find_edge(counts, order, thr):
    """
    在 order（列的遍历顺序）里找第一段"连续 EDGE_MIN_RUN 列、列高都 >= thr"的位置，
    返回这一段最靠外的那一列（即音频边缘）；找不到返回 None。
    """
    run = 0
    for i, x in enumerate(order):
        if counts[x] >= thr:
            run += 1
            if run >= cfg.EDGE_MIN_RUN:
                return order[i - run + 1]   # 这一段的起点（遍历方向上最先出现的那列）
        else:
            run = 0
    return None

def _extend_edge(counts, order, edge, thr, max_gap):
    """
    从主体边缘 edge 往外（order 的前面方向）延伸：
    只要外侧 max_gap 列之内还有列高 >= thr 的列，就把边缘推到那一列。
    用来保留渐强 / 渐弱的弱音，又不会把远处孤立的杂音带进来。
    """
    idx = order.index(edge)
    last, gap = edge, 0
    for x in reversed(order[:idx]):
        if counts[x] >= thr:
            last, gap = x, 0
        else:
            gap += 1
            if gap > max_gap:
                break
    return last


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

    # 3) 逐列统计波形像素（播放头、静音柱、中线都不会被算进去）
    cols = list(range(fl + 4, fr - 3))
    counts = {x: 0 if x in skip else sum(1 for y in range(ya, yb) if _is_wave(px[x, y]))
              for x in cols}
    peak = max(counts.values())
    if peak < cfg.MIN_COLUMN_PIXELS:
        return None, "没检测到音频波形"

    # 4) 按相对振幅找音频左右端：阈值 = 参考列高(百分位) × 比例
    ref = _reference_height(counts)
    thr_l = max(cfg.MIN_COLUMN_PIXELS, ref * cfg.EDGE_AMP_RATIO_L)
    thr_r = max(cfg.MIN_COLUMN_PIXELS, ref * cfg.EDGE_AMP_RATIO_R)
    audio_l = _find_edge(counts, cols, thr_l)
    audio_r = _find_edge(counts, cols[::-1], thr_r)
    if audio_l is None or audio_r is None or audio_l >= audio_r:
        return None, f"没找到有效音频边缘（最大列高={peak}，参考列高={ref}）"
        # 往外延伸，保留渐强 / 渐弱的弱音
    thr_tail = max(cfg.MIN_COLUMN_PIXELS, ref * cfg.EDGE_TAIL_RATIO)
    audio_l = _extend_edge(counts, cols, audio_l, thr_tail, cfg.EDGE_TAIL_GAP)
    audio_r = _extend_edge(counts, cols[::-1], audio_r, thr_tail, cfg.EDGE_TAIL_GAP)

    return {
        "top": top, "bottom": bottom, "fl": fl, "fr": fr,
        "bar_l": bar_l, "bar_r": bar_r,
        "audio_l": audio_l, "audio_r": audio_r,
        "peak": peak, "ref": ref, "thr_l": thr_l, "thr_r": thr_r,
        "dx_l": audio_l - (bar_l + cfg.BAR_GAP),   # 左静音柱需要右移（正）/ 左移（负）的像素
        "dx_r": audio_r - (bar_r - cfg.BAR_GAP),   # 右静音柱需要右移（正）/ 左移（负）的像素
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
    """识别音频真实起止 -> 拖动 -> 重新测量，直到左右静音柱都贴合音频（以静音柱位置为准）"""
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
              f"最大列高 {res['peak']}，参考列高 {res['ref']}，"
              f"阈值 {res['thr_l']:.1f}/{res['thr_r']:.1f}，"
              f"左柱需移动 {dx_l}px，右柱需移动 {dx_r}px")

        # 左右静音柱都已贴合：结束
        if abs(dx_l) <= cfg.FIT_TOLERANCE and abs(dx_r) <= cfg.FIT_TOLERANCE:
            print("✅ 静音柱已贴合音频")
            return
        if cfg.FIT_DRY_RUN:
            return

        center_y = y0 + (res["top"] + res["bottom"]) // 2
        if cfg.FIT_GRAB == "bar":
            # 直接抓静音柱本身
            grabs = ((x0 + res["bar_l"], dx_l), (x0 + res["bar_r"], dx_r))
        else:
            # 抓框左右边缘（往框内偏 1 像素，避免点到框外）
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