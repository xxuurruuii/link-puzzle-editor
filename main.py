# main.py
import pygame
import sys
import json
import time
import math
import tkinter as tk
from tkinter import filedialog
from solver import solve

# 导入拆分后的模块
from config import *
from ui import Button
from map_objects import ITEM_REGISTRY, Solve_mode # Solve_mode用于特殊的边缘逻辑初始化

class GridEditor:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("网格编辑器 (Modular)")
        self.clock = pygame.time.Clock()
        
        # 字体初始化 (自动寻找中文字体)
        f_path = pygame.font.match_font('simhei,microsoftyahei,arial')
        self.font = pygame.font.Font(f_path, 16) if f_path else pygame.font.SysFont('arial', 16)

        # 核心数据
        self.objects = [] 
        
        # 视图控制
        self.cam_x, self.cam_y = 50, 50
        
        # 交互状态
        self.selected_item_idx = 0 
        self.is_panning = False
        self.is_dragging_action = False
        self.drag_start_pos = (0,0)
        self.last_mouse_pos = (0,0)

        # 连线/边缘工具状态
        self.last_drag_grid = None  
        self.edge_op_mode = None    
        
        self.message = ""
        self.msg_timer = 0
        
        # 初始化界面
        self.buttons = []
        self.setup_ui()

    def setup_ui(self):
        """动态生成UI按钮"""
        x, y, w, h, gap = 10, 10, 100, 35, 5
        
        # 物品选择按钮
        for idx, cls in enumerate(ITEM_REGISTRY):
            self.buttons.append(Button(x, y, w, h, cls.name, self.font, idx))
            y += h + gap

        # 功能按钮
        funcs = [("CLEAR", "CLEAR"), ("LOAD", "IMPORT"), ("SAVE", "EXPORT"), ("SOLVE_ONE", "SOLVE"), ("DEDUCT", "DEDUCT")]
        for text, action in funcs:
            self.buttons.append(Button(x, y, w, h, text, self.font, action))
            y += h + gap

    def screen_to_grid(self, sx, sy, mode='cell'):
        """
        屏幕坐标 -> 网格坐标
        :param mode: 'cell' 使用向下取整(默认), 'vertex' 使用四舍五入(寻找最近格点)
        """
        if mode == 'vertex':
            # +0.5 实现四舍五入效果，或者直接用 round
            gx = round((sx - self.cam_x) / CELL_SIZE)
            gy = round((sy - self.cam_y) / CELL_SIZE)
            return int(gx), int(gy)
        else:
            # 默认 'cell' 或 'edge' 模式，保持原有的向下取整
            return (sx - self.cam_x) // CELL_SIZE, (sy - self.cam_y) // CELL_SIZE

    def grid_to_screen(self, gx, gy):
        """网格坐标 -> 屏幕坐标"""
        return gx * CELL_SIZE + self.cam_x, gy * CELL_SIZE + self.cam_y

    def show_msg(self, text):
        """显示临时反馈信息"""
        self.message = text
        self.msg_timer = time.time() + 2

    # --- 核心逻辑：对象管理 ---
    def place_object(self, new_obj):
        """放置物品，自动处理冲突和层级排序"""
        to_remove = []
        for obj in self.objects:
            if obj.gx == new_obj.gx and obj.gy == new_obj.gy:
                if obj.layer_id == new_obj.layer_id:
                    to_remove.append(obj)
        
        for obj in to_remove:
            self.objects.remove(obj)
        self.objects.append(new_obj)
        self.objects.sort(key=lambda o: o.z_index)

    def remove_object_at(self, gx, gy, target_layer_id=None):
        """删除指定位置的对象"""
        candidates = [o for o in self.objects if o.gx == gx and o.gy == gy]
        if not candidates: return

        if target_layer_id:
            # 针对特定层删除
            for obj in candidates:
                if obj.layer_id == target_layer_id:
                    self.objects.remove(obj)
        else:
            # 删除最上层
            candidates.sort(key=lambda o: o.z_index, reverse=True)
            if candidates:
                self.objects.remove(candidates[0])

    # --- 核心逻辑：文件I/O ---
    def save_map(self):
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")], title="保存"
        )
        root.destroy()
        if not file_path: return

        try:
            data = [obj.to_dict() for obj in self.objects]
            with open(file_path, "w", encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            self.show_msg(f"保存成功: {file_path.split('/')[-1]}")
        except Exception as e:
            print(e)
            self.show_msg("保存失败")

    def load_map_from_file(self):
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")], title="读取"
        )
        root.destroy()
        if not file_path: return

        try:
            with open(file_path, "r", encoding='utf-8') as f:
                data = json.load(f)
            
            self.objects = []
            name_map = {cls.__name__: cls for cls in ITEM_REGISTRY}
            
            for item_data in data:
                cls_name = item_data['type']
                if cls_name in name_map:
                    self.objects.append(name_map[cls_name].from_dict(item_data))
            
            self.objects.sort(key=lambda o: o.z_index)
            self.cam_x, self.cam_y = 50, 50
            self.show_msg(f"读取成功: {file_path.split('/')[-1]}")
        except Exception as e:
            print(e)
            self.show_msg("读取失败")

    # --- 核心逻辑：输入处理 ---
    def handle_input(self):
        mx, my = pygame.mouse.get_pos()
        current_cls = ITEM_REGISTRY[self.selected_item_idx]
        hgx, hgy = self.screen_to_grid(mx, my, current_cls.placement_type)

        is_simple_batch = (not current_cls.has_number 
                           and not current_cls.has_direction 
                           and not current_cls.is_continuous_tool)

        # 1. 按钮悬停更新
        for btn in self.buttons:
            btn.is_hovered = btn.rect.collidepoint((mx, my))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                sys.exit()

            # 2. 键盘事件 (修改数值)
            elif event.type == pygame.KEYDOWN:
                 if event.key == pygame.K_r: self.cam_x, self.cam_y = 50, 50
                 if event.unicode.isdigit():
                    current_cls = ITEM_REGISTRY[self.selected_item_idx]
                    # 查找当前鼠标下支持数字的物品 (Attribute-Driven)
                    candidates = [o for o in self.objects if o.gx == hgx and o.gy == hgy and o.has_number]
                    candidates.sort(key=lambda o: o.z_index, reverse=True)
                    if candidates:
                        # 修改最上层的一个
                        obj = candidates[0]
                        obj.data['num'] = int(event.unicode)
                        self.show_msg(f"数值设为 {event.unicode}")

            # 3. 鼠标按下
            elif event.type == pygame.MOUSEBUTTONDOWN:
                current_cls = ITEM_REGISTRY[self.selected_item_idx]

                # 左键点击
                if event.button == 1:
                    # A. 检查UI点击
                    clicked_ui = False
                    for btn in self.buttons:
                        if btn.rect.collidepoint(event.pos):
                            if btn.data == "EXPORT": self.save_map()
                            elif btn.data == "IMPORT": self.load_map_from_file()
                            elif btn.data == "CLEAR": 
                                self.objects = []
                                self.cam_x, self.cam_y = 50, 50
                                self.show_msg("已重置")
                            elif btn.data == "SOLVE":
                                # 1. 获取解
                                # 注意：这里我们传入当前的 self.objects 的字典形式
                                current_data = [obj.to_dict() for obj in self.objects]
                                solution_lines = solve(current_data)
                                
                                if solution_lines:
                                    
                                    # 2. 加载解
                                    for item_data in solution_lines:
                                        new_obj = Solve_mode.from_dict(item_data)
                                        self.objects.append(new_obj)
                                    
                                    # 3. 刷新排序
                                    self.objects.sort(key=lambda o: o.z_index)
                                    self.show_msg(f"求解成功，生成 {len(solution_lines)} 条线")
                                else:
                                    self.show_msg("未找到解")
                            elif btn.data == "DEDUCT":
                                # 1. 获取当前数据
                                current_data = [obj.to_dict() for obj in self.objects]
                                
                                # 2. 调用 deduct
                                from solver import deduct
                                hints = deduct(current_data)
                                
                                if hints:
                                    # 3. 将推理结果合并到盘面中
                                    # 注意：这里我们通常选择“追加”而不是“覆盖”，或者覆盖已有的 Solve_mode 对象
                                    # 这是一个策略选择，这里演示追加且不重复添加
                                    
                                    existing_signatures = set()
                                    for obj in self.objects:
                                        if obj.name == "Solve": # Solve_mode
                                            sig = (obj.gx, obj.gy, obj.data['dir'], obj.data['style'])
                                            existing_signatures.add(sig)
                                    
                                    count = 0
                                    for item in hints:
                                        sig = (item['x'], item['y'], item['data']['dir'], item['data']['style'])
                                        if sig not in existing_signatures:
                                            new_obj = Solve_mode.from_dict(item)
                                            self.place_object(new_obj) # place_object 会自动处理层级
                                            count += 1
                                    
                                    self.show_msg(f"推理完成，新增 {count} 处标记")
                                else:
                                    self.show_msg("推理完成，没有发现新的确定项")
                            else: self.selected_item_idx = btn.data
                            clicked_ui = True
                            break
                    if clicked_ui: continue

                    # B. 初始化拖拽操作
                    self.is_dragging_action = True
                    self.drag_start_pos = event.pos
                    self.drag_start_grid = (hgx, hgy) 
                    self.last_drag_grid = (hgx, hgy)

                    if is_simple_batch:
                        self.place_object(current_cls(hgx, hgy))
                    
                    # C. 连续工具初始化 (Attribute-Driven)
                    if current_cls.is_continuous_tool:
                        self.last_drag_grid = (hgx, hgy)
                        self.edge_op_mode = None

                # 中键平移
                elif event.button == 2:
                    self.is_panning = True
                    self.last_mouse_pos = event.pos
                
                # 右键删除/操作
                elif event.button == 3:
                    if current_cls.is_continuous_tool:
                        # 连续工具的右键也是一种操作起始 (如画叉)，逻辑同左键
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        self.edge_op_mode = None
                    elif is_simple_batch:
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        self.remove_object_at(hgx, hgy, target_layer_id=current_cls.layer_id)
                    else:
                        # 普通物品右键直接删除
                        self.remove_object_at(hgx, hgy, target_layer_id=current_cls.layer_id)

            # 4. 鼠标释放 (放置普通物品)
            elif event.type == pygame.MOUSEBUTTONUP:
                current_cls = ITEM_REGISTRY[self.selected_item_idx]
                
                # 仅处理：左键释放、非连续工具、且不在UI上
                if event.button == 1 and self.is_dragging_action and not current_cls.is_continuous_tool and not is_simple_batch:
                    if not any(b.rect.collidepoint(event.pos) for b in self.buttons):
                        start_gx, start_gy = self.drag_start_grid
                        new_obj = current_cls(start_gx, start_gy)
                        
                        # 调用物品自身的配置逻辑 (Attribute-Driven)
                        # 如果物品支持方向，它会自己计算
                        new_obj.configure_on_creation(self.drag_start_pos, event.pos)
                        
                        self.place_object(new_obj)

                self.is_dragging_action = False
                self.edge_op_mode = None
                self.last_drag_grid = None
                if event.button == 2: self.is_panning = False

            # 5. 鼠标移动
            elif event.type == pygame.MOUSEMOTION:
                # 视图平移
                if self.is_panning:
                    self.cam_x += event.pos[0] - self.last_mouse_pos[0]
                    self.cam_y += event.pos[1] - self.last_mouse_pos[1]
                    self.last_mouse_pos = event.pos

                if self.is_dragging_action:
                    # 1. 连续工具 (Edge)
                    if current_cls.is_continuous_tool:
                        self.handle_continuous_tool(hgx, hgy, current_cls)
                    
                    elif is_simple_batch:
                        # 只有移到了新格子才处理
                        if (hgx, hgy) != self.last_drag_grid:
                            is_left = pygame.mouse.get_pressed()[0]
                            is_right = pygame.mouse.get_pressed()[2]
                            
                            if is_left:
                                self.place_object(current_cls(hgx, hgy))
                            elif is_right:
                                self.remove_object_at(hgx, hgy, target_layer_id=current_cls.layer_id)
                            
                            self.last_drag_grid = (hgx, hgy)

    def handle_continuous_tool(self, curr_gx, curr_gy, tool_cls):
        """处理连续拖拽工具的逻辑 (如边缘连线)"""
        prev_gx, prev_gy = self.last_drag_grid
        if (curr_gx, curr_gy) == (prev_gx, prev_gy):
            return

        # 1. 确定操作对象 (EdgeItem) 的位置和方向
        target_obj = None
        if curr_gx == prev_gx + 1 and curr_gy == prev_gy:
            target_obj = tool_cls(prev_gx, prev_gy, 'right')
        elif curr_gx == prev_gx - 1 and curr_gy == prev_gy:
            target_obj = tool_cls(curr_gx, curr_gy, 'right')
        elif curr_gx == prev_gx and curr_gy == prev_gy + 1:
            target_obj = tool_cls(prev_gx, prev_gy, 'down')
        elif curr_gx == prev_gx and curr_gy == prev_gy - 1:
            target_obj = tool_cls(curr_gx, curr_gy, 'down')
        
        if target_obj:
            # 2. 检查现有物品
            existing = None
            for obj in self.objects:
                if obj.gx == target_obj.gx and obj.gy == target_obj.gy and obj.layer_id == target_obj.layer_id:
                    existing = obj
                    break
            
            # 3. 确定操作模式 (仅在第一次移动时确定)
            is_right_btn = pygame.mouse.get_pressed()[2]
            if self.edge_op_mode is None:
                if is_right_btn:
                    if existing and existing.data.get('style') == 'cross':
                        self.edge_op_mode = 'del_cross'
                    else:
                        self.edge_op_mode = 'draw_cross'
                else:
                    if existing and existing.data.get('style') == 'line':
                        self.edge_op_mode = 'del_line'
                    else:
                        self.edge_op_mode = 'draw_line'

            # 4. 执行操作
            if self.edge_op_mode == 'del_line' and existing and existing.data.get('style') == 'line':
                self.objects.remove(existing)
            elif self.edge_op_mode == 'del_cross' and existing and existing.data.get('style') == 'cross':
                self.objects.remove(existing)
            elif self.edge_op_mode == 'draw_line':
                target_obj.data['style'] = 'line'
                self.place_object(target_obj)
            elif self.edge_op_mode == 'draw_cross':
                target_obj.data['style'] = 'cross'
                self.place_object(target_obj)

        self.last_drag_grid = (curr_gx, curr_gy)

    def draw(self):
        self.screen.fill(BG_COLOR)
        
        # 1. 绘制所有物品
        for obj in self.objects:
            sx, sy = self.grid_to_screen(obj.gx, obj.gy)
            # 视锥剔除优化
            if -CELL_SIZE < sx < SCREEN_WIDTH and -CELL_SIZE < sy < SCREEN_HEIGHT:
                obj.draw(self.screen, self.cam_x, self.cam_y)

        # 2. 绘制幽灵光标 (Attribute-Driven)
        mx, my = pygame.mouse.get_pos()
        on_ui = any(b.rect.collidepoint((mx, my)) for b in self.buttons)
        
        if not on_ui:
            current_cls = ITEM_REGISTRY[self.selected_item_idx]
            hgx, hgy = self.screen_to_grid(mx, my, current_cls.placement_type)
            sx, sy = self.grid_to_screen(hgx, hgy)
            
            
            if current_cls.placement_type == 'vertex':
                # 格点光标
                pygame.draw.circle(self.screen, (150, 150, 150), (sx, sy), 6)
            elif current_cls.placement_type == 'cell':
                # 格内光标
                pygame.draw.rect(self.screen, (100, 100, 100), (sx, sy, CELL_SIZE, CELL_SIZE), 2)
            # 'edge' 类型通常不需要特定光标，或者可以添加特定的点

        # 3. 绘制拖拽辅助线 (Attribute-Driven)
        current_cls = ITEM_REGISTRY[self.selected_item_idx]
        if self.is_dragging_action and current_cls.has_direction:
             pygame.draw.line(self.screen, (255, 255, 0), self.drag_start_pos, pygame.mouse.get_pos(), 2)

        # 4. 绘制UI
        for btn in self.buttons:
            is_sel = (btn.data == self.selected_item_idx)
            btn.draw(self.screen, is_sel)
            
        if time.time() < self.msg_timer:
            s = self.font.render(self.message, True, (0, 255, 0))
            self.screen.blit(s, (10, SCREEN_HEIGHT - 30))

        pygame.display.flip()

    def run(self):
        while True:
            self.handle_input()
            self.draw()
            self.clock.tick(60)

if __name__ == "__main__":
    GridEditor().run()