# -*- coding: utf-8 -*-
"""id_store.py —— 编号提取与保存"""
import os
import re
import time
from datetime import datetime

import pyautogui
import pyperclip

import config as cfg
from state import state
from winutil import get_desktop_path


class IdStore:
    def __init__(self):
        today = datetime.now()   # 读取系统当前日期
        # 每行一个编号，按日期命名
        self.path = os.path.join(get_desktop_path(), f"标注编号{today.month}.{today.day}.txt")
        self.saved_ids = set()
        self.record_count = 0
        self.write_enabled = True    # 是否把编号写入文本文件（界面开关控制，默认开启）
        self.session_ids = set()     # 本次运行里已计过数的编号（关闭写入时也能去重）

    def load(self):
        """创建文件（已存在则保留原内容），并读取已有编号用于去重"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8"):
            pass
        with open(self.path, "r", encoding="utf-8") as f:
            self.saved_ids = {line.strip() for line in f if line.strip()}
        self.record_count = len(self.saved_ids)

    def extract(self):
        """双击选中页面底部的编号 -> 复制 -> 读剪贴板 -> 追加写入 txt

        返回值：True = 这是一个新编号（已写入文件）；
               False = 没读到编号 / 编号已记录过（重复） / 出错，都不算新完成的一条
        """
        try:
            with state.mouse_lock:
                pyperclip.copy("")  # 先清空剪贴板，避免读到上一次的旧内容
                pyautogui.doubleClick(cfg.ID_POS[0], cfg.ID_POS[1])
                time.sleep(0.15)
                pyautogui.hotkey('ctrl', 'c')
                time.sleep(0.15)
                raw = pyperclip.paste()

            m = re.search(r"\d+", raw or "")
            if not m:
                print(f"⚠️ 没读到编号，剪贴板内容：{raw!r}")
                return False
            num = m.group()

            counted_before = num in self.session_ids

            if self.write_enabled:
                # 编号已记录过（同一页重复触发，或重启脚本后重复）则不重复写入
                if num in self.saved_ids:
                    print(f"⚠️ 编号 {num} 已记录过，跳过")
                    return False
                self.saved_ids.add(num)
                self.record_count += 1
                self.session_ids.add(num)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(num + "\n")
                print(f"📝 已保存第 {self.record_count} 条：{num}")
                return not counted_before     # 关闭写入期间已计过数的编号，补写文件但不重复计数

            # 写入已关闭：只读编号并在内存里去重，不写文件
            if num in self.saved_ids or counted_before:
                print(f"⚠️ 编号 {num} 已记录过，跳过")
                return False
            self.session_ids.add(num)
            print(f"📝 新编号 {num}（写入文本已关闭，未保存到文件）")
            return True
        except Exception as e:
            print("⚠️ 提取编号失败：", e)
            return False


store = IdStore()