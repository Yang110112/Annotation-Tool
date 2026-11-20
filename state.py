# -*- coding: utf-8 -*-
"""state.py —— 运行时共享状态"""
import threading


class State:
    def __init__(self):
        # 各任务独立的运行标志
        self.auto_running = False
        self.replay_running = False
        self.speed_running = False
        self.last_wheel_time = 0.0
        # 当前是否处于 1.25 倍速（脚本记录，默认 False = 1 倍速）
        self.speed_fast = False
        # 鼠标操作锁：同一时刻只允许一个任务操作鼠标
        self.mouse_lock = threading.RLock()


state = State()