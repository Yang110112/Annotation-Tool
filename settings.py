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

# 默认按键：右键 = 自动化，滚轮 = 重听
DEFAULT_BINDINGS = {
    "auto": {"type": "mouse", "code": "right", "name": MOUSE_NAMES["right"]},
    "replay": {"type": "mouse", "code": "wheel_any", "name": MOUSE_NAMES["wheel_any"]},
}


def load_settings(default_keywords):
    cfg = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    return {
        "bindings": {
            "auto": cfg.get("auto") or DEFAULT_BINDINGS["auto"],
            "replay": cfg.get("replay") or DEFAULT_BINDINGS["replay"],
        },
        "keywords": cfg.get("keywords") or list(default_keywords),
        "suppress": bool(cfg.get("suppress", True)),
    }


def save_settings(bindings, keywords, suppress):
    cfg = {
        "auto": bindings["auto"],
        "replay": bindings["replay"],
        "keywords": keywords,
        "suppress": suppress,
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ 保存配置失败：", e)