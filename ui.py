# ui.py
import pygame
from config import *

class Button:
    """
    简单的UI按钮类
    负责绘制按钮背景、边框及文字，并处理悬停状态
    """
    def __init__(self, x, y, w, h, text, font, callback_data):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.font = font
        self.data = callback_data # 按钮绑定的数据（如物品索引或功能字符串）
        self.is_hovered = False

    def draw(self, screen, is_selected):
        """
        绘制按钮
        :param is_selected: 是否处于被选中状态（影响颜色）
        """
        # 决定背景颜色
        if is_selected:
            color = BTN_ACTIVE
        elif self.is_hovered:
            color = BTN_HOVER
        else:
            color = BTN_COLOR

        # 绘制背景和边框
        pygame.draw.rect(screen, color, self.rect, border_radius=5)
        pygame.draw.rect(screen, (150, 150, 150), self.rect, 1, border_radius=5)
        
        # 绘制文字居中
        surf = self.font.render(self.text, True, TEXT_COLOR)
        screen.blit(surf, surf.get_rect(center=self.rect.center))