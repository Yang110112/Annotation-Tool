# -*- coding: utf-8 -*-
"""config.py —— 所有可调参数集中在这里"""

# ====== 窗口匹配 ======
# 只有当前窗口标题包含下面任意一个关键词时，快捷键才生效
# 标注页标题示例："赣州-区域3-单人转写标注-汇智 标注任务 - Microsoft Edge"
TARGET_KEYWORDS = ["单人转写标注"]
# True：每次触发都会打印当前窗口标题，方便确认关键词是否写对
DEBUG_TITLE = True

# ====== 编号提取 ======
ID_POS = (172, 1014)        # 页面底部"编号：xxxxx"中数字的坐标，双击选中

# ====== 滚轮 ======
SUPPRESS_WHEEL = True       # 仅在标注页窗口内生效；True：滚轮不会再滚动页面/缩放波形
WHEEL_COOLDOWN = 0.8        # 滚一格会连续产生多个事件，冷却期内只触发一次

# ====== 倍速 ======
SPEED_INPUT_POS = (1473, 305)   # 倍速输入框坐标（"倍速：1.00"中数字所在位置）
FAST_SPEED = "1.25"             # 第一次按 Tab 设置的倍速
NORMAL_SPEED = "1"              # 再按一次 Tab 恢复的倍速
# True：每次自动化后，把脚本记录的状态重置为"正常倍速"（换题后页面倍速会回到 1 倍时用）
# 如果换题后页面倍速保持不变，改成 False
RESET_SPEED_ON_NEW_PAGE = True

# ====== 自动化点击流程 ======
REPLAY_POS = (179, 256)         # 选中语句 / 重听音频
CLICK_SEQUENCE = [              # 贴合静音柱之后依次点击的坐标
    (393, 470),
    (393, 567),
    (524, 658),
    (524, 750),
    (524, 840),
    (1845, 724),
    (1777, 953),
]
TRANSCRIBE_BOX_POS = (651, 943) # 转写框
PARK_POS = (1717, 1017)         # 粘贴完成后鼠标停靠位置
AFTER_TASK_WAIT = 5             # 自动化结束后等待秒数（期间滚轮可立即重听）

# ====== 静音柱贴合 ======
FIT_ENABLED = True
FIT_DRY_RUN = False           # True：只检测并打印，不拖动
# 波形区截图范围（屏幕坐标）
SCAN_X0, SCAN_Y0 = 380, 150
SCAN_W, SCAN_H = 1260, 125
BAR_MIN_HEIGHT = 30           # 静音柱竖线至少多少像素高
MIN_COLUMN_PIXELS = 3         # 一列里波形像素不少于多少个，才算"有音频"
FIT_TOLERANCE = 3             # 偏差不超过这个像素数就不拖
FIT_MAX_DRAG = 300            # 单次拖动超过这个像素数视为识别异常，不拖动
BAR_GAP = 3                   # 贴合后，静音柱与音频最边缘之间保留的像素
EDGE_AMP_RATIO_L = 0.2        # 左边缘：列高需达到"参考列高"的这个比例
EDGE_AMP_RATIO_R = 0.2  
EDGE_TAIL_RATIO = 0.05        # 新增：往外延伸时的低阈值（参考列高的比例）
EDGE_TAIL_GAP = 6             # 新增：延伸时允许的最大间隔列数      # 右边缘：同上
EDGE_REF_PERCENTILE = 90      # 新增：参考列高取有声列高度的第几百分位
EDGE_MIN_RUN = 4              # 需要连续多少列都达标，才算音频边缘（过滤又窄又高的毛刺）
FIT_GRAB = "edge"             # 拖动时抓取的位置："edge" = 框左右边缘；"bar" = 静音柱本身
FIT_MAX_ROUNDS = 3            # 最多测量并修正几轮（每轮拖完会重新截图检查静音柱是否贴合）