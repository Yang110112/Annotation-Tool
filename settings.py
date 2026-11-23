# -*- coding: utf-8 -*-
"""settings.py —— GUI 的按键配置读写（hotkey_config.json 格式与旧版完全兼容）"""
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hotkey_config.json")

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

# 弹窗提醒的默认条数（界面可修改，会保存）
DEFAULT_MILESTONE = 100

# 所有可设置按键的功能（顺序即界面显示顺序）
ACTIONS = ("auto", "replay", "speed")

# 默认按键：右键 = 自动化，滚轮 = 重听，单按 Ctrl = 倍速切换
# code 为 "ctrl" 表示"单按一下 Ctrl（按下后松开，期间没按其他键）"
DEFAULT_BINDINGS = {
    "auto": {"type": "mouse", "code": "right", "name": MOUSE_NAMES["right"]},
    "replay": {"type": "mouse", "code": "wheel_any", "name": MOUSE_NAMES["wheel_any"]},
    "speed": {"type": "key", "code": "ctrl", "name": "Ctrl（单按）"},
}


def load_settings(default_keywords):
    cfg = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    try:
        milestone = int(cfg.get("milestone", DEFAULT_MILESTONE))
    except (TypeError, ValueError):
        milestone = DEFAULT_MILESTONE
    if not 1 <= milestone <= 99999:
        milestone = DEFAULT_MILESTONE
    return {
        "milestone": milestone,
        # 旧配置文件里没有 speed 字段时，自动使用默认值（Ctrl 单按），行为和旧版一致
        "bindings": {a: cfg.get(a) or DEFAULT_BINDINGS[a] for a in ACTIONS},
        "keywords": cfg.get("keywords") or list(default_keywords),
        "suppress": bool(cfg.get("suppress", True)),
    }


def save_settings(bindings, keywords, suppress, milestone=DEFAULT_MILESTONE):
    cfg = {a: bindings[a] for a in ACTIONS}
    cfg["keywords"] = keywords
    cfg["suppress"] = suppress
    cfg["milestone"] = milestone
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ 保存配置失败：", e)