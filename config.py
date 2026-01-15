# config.py
"""
全局配置参数文件
包含屏幕尺寸、颜色定义及网格参数
"""

# 屏幕与网格
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 700
DEFAULT_CELL_SIZE = 50

# 颜色定义 (R, G, B)
BG_COLOR = (30, 30, 60)         # 背景深蓝
CELL_COLOR = (240, 240, 240)    # 格子填充色
HOVER_COLOR = (200, 200, 200)   # 鼠标悬停高亮
TEXT_COLOR = (255, 255, 255)    # 文字颜色

# 按钮颜色
BTN_COLOR = (60, 60, 60)
BTN_ACTIVE = (0, 120, 215)
BTN_HOVER = (80, 80, 80)

# --- UI 布局配置 ---
UI_SIDEBAR_WIDTH = 120       # 左侧面板的总宽度
UI_MARGIN = 5                # 边缘间距
UI_GAP = 5                   # 按钮之间的垂直间距

# 标签页按钮 (Tabs)
TAB_HEIGHT = 25              # 顶部标签的高度
TAB_WIDTH = 40

# 功能/物品按钮
BTN_HEIGHT = 35              # 列表按钮的高度
BTN_WIDTH = UI_SIDEBAR_WIDTH - (UI_MARGIN * 2) # 自动计算按钮宽度以填满侧边栏