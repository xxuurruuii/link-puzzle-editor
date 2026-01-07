# map_objects.py
import pygame
import math
from config import *

class MapObject:
    """
    所有可放置物品的基类
    定义了物品的通用属性和序列化接口
    """
    name = "Base"
    layer_id = "default"  # 冲突层级：同ID互斥
    z_index = 0           # 渲染层级：越大越靠上
    
    # --- 行为属性开关 (主程序通过检查这些属性来决定交互逻辑) ---
    placement_type = "cell"  # 'cell'(格内), 'vertex'(格点), 'edge'(边缘工具)
    has_number = False       # 是否支持通过数字键修改数值
    has_direction = False    # 是否支持通过拖拽设定方向
    is_continuous_tool = False # 是否是连续绘图工具 (如画线)

    def __init__(self, gx, gy):
        self.gx = gx
        self.gy = gy
        self.data = {} 

    def draw(self, screen, cam_x, cam_y):
        """子类需实现具体的绘制逻辑"""
        pass

    def configure_on_creation(self, start_pos, end_pos):
        """
        当物品被创建（鼠标松开）时调用。
        如果 items 需要根据鼠标拖拽的轨迹改变初始状态（如箭头方向），在此实现。
        :param start_pos: 鼠标按下的屏幕坐标 (x, y)
        :param end_pos: 鼠标松开的屏幕坐标 (x, y)
        """
        pass

    def to_dict(self):
        """序列化为字典"""
        return {
            "type": self.__class__.__name__,
            "x": self.gx,
            "y": self.gy,
            "data": self.data
        }

    @classmethod
    def from_dict(cls, data):
        """从字典反序列化"""
        obj = cls(data['x'], data['y'])
        obj.data = data.get('data', {})
        return obj

    def get_screen_pos(self, cam_x, cam_y):
        """获取物品逻辑坐标对应的屏幕像素坐标 (左上角)"""
        return self.gx * CELL_SIZE + cam_x, self.gy * CELL_SIZE + cam_y


# --- 具体物品实现 ---

class FloorCell(MapObject):
    name = "格子"
    layer_id = "floor"
    z_index = 0
    placement_type = "cell"

    def draw(self, screen, cam_x, cam_y):
        sx, sy = self.get_screen_pos(cam_x, cam_y)
        rect = pygame.Rect(sx, sy, CELL_SIZE, CELL_SIZE)
        pygame.draw.rect(screen, CELL_COLOR, rect)
        pygame.draw.rect(screen, (200, 200, 200), rect, 2)


class Simpleloop(MapObject):
    name = "Simpleloop"
    layer_id = "floor_simpleloop"
    z_index = 5
    placement_type = "cell"

    def draw(self, screen, cam_x, cam_y):
        sx, sy = self.get_screen_pos(cam_x, cam_y)
        s = pygame.Surface((CELL_SIZE, CELL_SIZE))
        s.set_alpha(30) # 设置半透明
        s.fill((0, 255, 0)) 
        screen.blit(s, (sx, sy))


class EndPoint(MapObject):
    name = "端点"
    layer_id = "cell_center"
    z_index = 10
    placement_type = "cell"
    has_number = True      # 开启数字编辑

    def __init__(self, gx, gy):
        super().__init__(gx, gy)
        self.data['num'] = 1

    def draw(self, screen, cam_x, cam_y):
        sx, sy = self.get_screen_pos(cam_x, cam_y)
        center = (sx + CELL_SIZE // 2, sy + CELL_SIZE // 2)
        
        # 1. 绘制背景圆
        pygame.draw.circle(screen, (255, 100, 100), center, int(CELL_SIZE * 0.3))
        
        # 2. 绘制数字
        font = pygame.font.SysFont('Arial', 16, bold=True)
        # 使用白色文字 (255, 255, 255) 以便在红底上清晰显示，如果背景色浅也可以改用黑色
        txt = font.render(str(self.data.get('num', 1)), True, (255, 255, 255))
        txt_rect = txt.get_rect(center=center)
        screen.blit(txt, txt_rect)


class YajilinArrow(MapObject):
    name = "Yajilin"
    layer_id = "cell_center"
    z_index = 10
    placement_type = "cell"
    has_number = True      # 开启数字编辑
    has_direction = True   # 开启方向拖拽

    def __init__(self, gx, gy):
        super().__init__(gx, gy)
        self.data['num'] = 1
        self.data['dir'] = 'up'

    def configure_on_creation(self, start_pos, end_pos):
        """根据拖拽向量计算箭头方向"""
        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        if math.hypot(dx, dy) > 20: # 拖拽距离超过阈值才改变方向
            if abs(dx) > abs(dy):
                self.data['dir'] = 'right' if dx > 0 else 'left'
            else:
                self.data['dir'] = 'down' if dy > 0 else 'up'

    def draw(self, screen, cam_x, cam_y):
        sx, sy = self.get_screen_pos(cam_x, cam_y)
        cx, cy = sx + CELL_SIZE//2, sy + CELL_SIZE//2
        
        # 绘制背景
        pygame.draw.circle(screen, (240, 240, 240), (cx, cy), int(CELL_SIZE * 0.4))
        pygame.draw.circle(screen, (50, 50, 50), (cx, cy), int(CELL_SIZE * 0.4), 2)
        
        # 绘制数字
        font = pygame.font.SysFont('Arial', 14, bold=True)
        txt = font.render(str(self.data['num']), True, (0, 0, 0))
        screen.blit(txt, txt.get_rect(center=(cx, cy)))

        # 绘制三角形箭头
        offset = CELL_SIZE * 0.35
        pts = []
        d = self.data['dir']
        if d == 'up': pts = [(cx, cy-offset), (cx-5, cy-offset+8), (cx+5, cy-offset+8)]
        elif d == 'down': pts = [(cx, cy+offset), (cx-5, cy+offset-8), (cx+5, cy+offset-8)]
        elif d == 'left': pts = [(cx-offset, cy), (cx-offset+8, cy-5), (cx-offset+8, cy+5)]
        elif d == 'right': pts = [(cx+offset, cy), (cx+offset-8, cy-5), (cx+offset-8, cy+5)]
        
        if pts: pygame.draw.polygon(screen, (0, 0, 200), pts)


class Slitherlink(MapObject):
    name = "Slitherlink"
    layer_id = "vertex"
    z_index = 20
    placement_type = "vertex" # 标记为格点物品
    has_number = True

    def __init__(self, gx, gy):
        super().__init__(gx, gy)
        self.data['num'] = 1

    def draw(self, screen, cam_x, cam_y):
        sx, sy = self.get_screen_pos(cam_x, cam_y)
        # 绘制在交叉点的小方块
        rect = pygame.Rect(0, 0, 24, 24)
        rect.center = (sx, sy) 
        pygame.draw.rect(screen, (255, 255, 255), rect)
        pygame.draw.rect(screen, (0, 0, 0), rect, 2)
        
        font = pygame.font.SysFont('Arial', 16, bold=True)
        txt = font.render(str(self.data['num']), True, (0, 0, 0))
        screen.blit(txt, txt.get_rect(center=rect.center))


class Solve_mode(MapObject):
    """画线/画叉工具 (特殊的连续操作物品)"""
    name = "TrySolve"
    z_index = 100
    placement_type = "edge"
    is_continuous_tool = True # 标记为连续工具

    def __init__(self, gx, gy, direction='right', style='line'):
        super().__init__(gx, gy)
        self.data['dir'] = direction  # 'right' or 'down'
        self.data['style'] = style    # 'line' or 'cross'
        self.layer_id = f"edge_{direction}" # 动态层级

    def draw(self, screen, cam_x, cam_y):
        sx, sy = self.get_screen_pos(cam_x, cam_y)
        color = (63, 72, 204) if self.data['style'] == 'line' else (255, 50, 50)
        width = 4
        
        start_pos, end_pos = None, None
        # 修正坐标计算逻辑：从格子的中心点开始连线
        if self.data['dir'] == 'right':
            start_pos = (sx + CELL_SIZE / 2, sy + CELL_SIZE / 2)
            end_pos = (sx + CELL_SIZE * 3 / 2, sy + CELL_SIZE / 2)
        elif self.data['dir'] == 'down':
            start_pos = (sx + CELL_SIZE / 2, sy + CELL_SIZE / 2)
            end_pos = (sx + CELL_SIZE / 2, sy + CELL_SIZE * 3 / 2)
            
        if self.data['style'] == 'line':
            pygame.draw.line(screen, color, start_pos, end_pos, width)
        else:
            # 画叉
            mid_x = (start_pos[0] + end_pos[0]) // 2
            mid_y = (start_pos[1] + end_pos[1]) // 2
            offset = 6
            pygame.draw.line(screen, color, (mid_x - offset, mid_y - offset), (mid_x + offset, mid_y + offset), 2)
            pygame.draw.line(screen, color, (mid_x - offset, mid_y + offset), (mid_x + offset, mid_y - offset), 2)

# --- 注册表 ---
# 如果添加新物品，只需在这里注册，并在上面定义类即可
ITEM_REGISTRY = [FloorCell, EndPoint, YajilinArrow, Simpleloop, Slitherlink, Solve_mode]