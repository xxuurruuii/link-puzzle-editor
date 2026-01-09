# renderer.py
import pygame
import time
from config import *
from map_objects import ITEM_REGISTRY

def render_scene(editor):
    """渲染主循环的一帧"""
    screen = editor.screen
    screen.fill(BG_COLOR)
    
    # 1. 绘制所有地图物品
    for obj in editor.objects:
        sx, sy = editor.grid_to_screen(obj.gx, obj.gy)
        # 视锥剔除 (Off-screen culling)
        if -CELL_SIZE < sx < SCREEN_WIDTH and -CELL_SIZE < sy < SCREEN_HEIGHT:
            obj.draw(screen, editor.cam_x, editor.cam_y)

    # 2. 绘制幽灵光标 (预览位置)
    mx, my = pygame.mouse.get_pos()
    on_ui = any(b.rect.collidepoint((mx, my)) for b in editor.buttons)
    
    if not on_ui:
        current_cls = ITEM_REGISTRY[editor.selected_item_idx]
        hgx, hgy = editor.screen_to_grid(mx, my, current_cls.placement_type)
        sx, sy = editor.grid_to_screen(hgx, hgy)
        
        # 创建一个全屏大小的透明层用于绘制半透明光标
        # 注意: (R, G, B, A) 中的 A 控制透明度 (0-255)
        ghost_surf = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        
        if current_cls.placement_type == 'vertex':
            # 格点光标: 空心圆形, 半透明灰色
            pygame.draw.circle(ghost_surf, (150, 150, 150, 150), (sx, sy), 16, 2)
        elif current_cls.placement_type == 'cell':
            # 格内光标: 半透明边框矩形
            pygame.draw.rect(ghost_surf, (100, 100, 100, 150), (sx, sy, CELL_SIZE, CELL_SIZE), 2)
        
        # 将绘制好的半透明层叠加到主屏幕上
        screen.blit(ghost_surf, (0, 0))

    # 3. 绘制拖拽辅助线 (如箭头方向指示)
    current_cls = ITEM_REGISTRY[editor.selected_item_idx]
    if editor.is_dragging_action and current_cls.has_direction:
            pygame.draw.line(screen, (255, 255, 0), editor.drag_start_pos, pygame.mouse.get_pos(), 2)

    # 4. 绘制 UI 按钮
    for btn in editor.buttons:
        is_sel = (btn.data == editor.selected_item_idx)
        btn.draw(screen, is_sel)
        
    # 5. 绘制底部临时消息
    if time.time() < editor.msg_timer:
        s = editor.font.render(editor.message, True, (0, 255, 0))
        screen.blit(s, (10, SCREEN_HEIGHT - 30))

    pygame.display.flip()