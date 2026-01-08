# main.py
# 网格谜题编辑器主程序
# 负责界面渲染、用户交互、文件I/O以及与求解器进程的通信

import pygame
import sys
import json
import time
import math
import tkinter as tk
from tkinter import filedialog
from solver import solve, deduct
import multiprocessing
import tkinter.ttk as ttk

# --- 自定义模块导入 ---
from config import *
from ui import Button
from map_objects import ITEM_REGISTRY, Solve_mode # Solve_mode用于特殊的边缘逻辑初始化

# --- 全局函数：多进程工作入口 ---
def solver_worker(mode, data, queue):
    """
    运行在独立进程中的求解任务包装器。
    由于 Windows 下 multiprocessing 的 pickling 限制，必须定义在全局作用域。
    
    :param mode: 'SOLVE' (求解) 或 'DEDUCT' (逻辑推演)
    :param data: 序列化后的盘面数据 (List[Dict])
    :param queue: 用于回传结果的通信队列
    """
    # 在子进程中重新导入 solver，确保环境独立
    import solver 
    try:
        result = []
        if mode == "SOLVE":
            result = solver.solve(data)
        elif mode == "DEDUCT":
            result = solver.deduct(data)
        queue.put(result)
    except Exception as e:
        print(f"Worker Error: {e}")
        queue.put(None) # 发生异常时发送 None

class GridEditor:
    def __init__(self):
        # 1. Pygame 环境初始化
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("网格编辑器")
        self.clock = pygame.time.Clock()
        
        # 字体初始化 (优先尝试中文系统字体，后备 Arial)
        f_path = pygame.font.match_font('simhei,microsoftyahei,arial')
        self.font = pygame.font.Font(f_path, 16) if f_path else pygame.font.SysFont('arial', 16)

        # 2. 核心数据结构
        self.objects = [] # 存储所有 MapObject 实例
        
        # 3. 视图控制参数
        self.cam_x, self.cam_y = 50, 50 # 摄像机偏移量
        
        # 4. 交互状态标志
        self.selected_item_idx = 0     # 当前选中的工具索引
        self.is_panning = False        # 是否正在平移视图 (中键)
        self.is_dragging_action = False # 是否正在执行拖拽操作 (左键/右键)
        self.drag_start_pos = (0,0)    # 拖拽起始屏幕坐标
        self.last_mouse_pos = (0,0)    # 上一帧鼠标位置 (用于平移计算)

        # 5. 连线/边缘工具专用状态
        self.last_drag_grid = None     # 上一次处理过的网格坐标 (防止重复处理)
        self.edge_op_mode = None       # 边缘操作模式 (如 'draw_line', 'del_cross' 等)
        
        # 6. 消息提示系统
        self.message = ""
        self.msg_timer = 0
        
        # 7. UI 初始化
        self.buttons = []
        self.setup_ui()

    def setup_ui(self):
        """动态生成左侧工具栏按钮"""
        x, y, w, h, gap = 10, 10, 100, 35, 5
        
        # A. 物品选择按钮 (来自 map_objects.py 的注册表)
        for idx, cls in enumerate(ITEM_REGISTRY):
            self.buttons.append(Button(x, y, w, h, cls.name, self.font, idx))
            y += h + gap

        # B. 功能控制按钮
        funcs = [("清空", "WIPE"), ("!重置", "CLEAR"), ("LOAD", "IMPORT"), ("SAVE", "EXPORT"), ("SOLVE_ONE", "SOLVE"), ("DEDUCT", "DEDUCT")]
        for text, action in funcs:
            self.buttons.append(Button(x, y, w, h, text, self.font, action))
            y += h + gap

    def screen_to_grid(self, sx, sy, mode='cell'):
        """
        坐标转换：屏幕像素坐标 -> 逻辑网格坐标
        :param sx, sy: 屏幕坐标
        :param mode: 
            - 'cell': 格内物品 (如数字、地板)，使用向下取整
            - 'vertex': 格点物品 (如 Slitherlink)，使用四舍五入寻找最近交叉点
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
        """坐标转换：逻辑网格坐标 -> 屏幕像素坐标 (左上角或中心点取决于具体绘制逻辑)"""
        return gx * CELL_SIZE + self.cam_x, gy * CELL_SIZE + self.cam_y

    def show_msg(self, text):
        """在屏幕底部显示临时反馈信息"""
        self.message = text
        self.msg_timer = time.time() + 2

    # --- 对象管理逻辑 ---
    
    def place_object(self, new_obj):
        """
        放置新物品到盘面
        功能：
        1. 检测并移除同一层级(layer_id)下的旧物品 (冲突处理)
        2. 添加新物品
        3. 根据 z_index 重新排序渲染列表
        """
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
        """
        删除指定位置的对象
        :param target_layer_id: 如果指定，仅删除该层级的物品；否则删除该位置最上层的物品。
        """
        candidates = [o for o in self.objects if o.gx == gx and o.gy == gy]
        if not candidates: return

        if target_layer_id:
            # 针对特定层删除
            for obj in candidates:
                if obj.layer_id == target_layer_id:
                    self.objects.remove(obj)
        else:
            # 删除最上层 (z-index 最大)
            candidates.sort(key=lambda o: o.z_index, reverse=True)
            if candidates:
                self.objects.remove(candidates[0])

    # --- 文件 I/O ---
    
    def save_map(self):
        """弹出文件对话框保存当前盘面为 JSON"""
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
        """弹出文件对话框读取 JSON 并重建盘面"""
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

    # --- 异步求解逻辑 ---
    
    def run_async_solver(self, mode):
        """
        启动子进程进行计算，并显示模态对话框冻结主界面。
        :param mode: 'SOLVE' 或 'DEDUCT'
        :return: 求解结果 (List) 或 None (被中止)
        """
        # 1. 准备数据 (仅传递纯数据，不要传递 Pygame 对象，避免 Pickling 错误)
        current_data = [obj.to_dict() for obj in self.objects]
        
        # 2. 初始化多进程组件
        queue = multiprocessing.Queue()
        process = multiprocessing.Process(target=solver_worker, args=(mode, current_data, queue))
        process.start()
        
        # 3. 创建 Tkinter 模态弹窗
        root = tk.Tk()
        root.withdraw()  # 隐藏 Tkinter 主窗口
        
        popup = tk.Toplevel(root)
        popup.title("正在计算...")
        popup.geometry("300x120")
        # 居中显示
        x = (root.winfo_screenwidth() // 2) - 150
        y = (root.winfo_screenheight() // 2) - 60
        popup.geometry(f"+{x}+{y}")
        popup.grab_set()  # 捕获输入焦点，阻止与 Pygame 主程序交互
        popup.resizable(False, False)

        # 界面元素
        lbl = tk.Label(popup, text=f"正在运行 {mode} 逻辑...\n请稍候 (复杂盘面可能耗时较长)", pady=20)
        lbl.pack()

        # 状态变量
        self.solver_result = None
        is_aborted = False

        # 中止操作回调
        def on_abort():
            nonlocal is_aborted
            is_aborted = True
            if process.is_alive():
                process.terminate() # 强制杀死子进程 (Z3 计算也会随之停止)
                process.join()
            popup.destroy()
            root.destroy()
            self.show_msg("操作已中止")

        btn = ttk.Button(popup, text="中止 (Force Stop)", command=on_abort)
        btn.pack(pady=5)

        # 4. 自定义事件循环 (阻塞 Pygame 逻辑，但保持 Tkinter 响应)
        while True:
            try:
                # 刷新弹窗界面
                popup.update()
                popup.update_idletasks()
                
                # 检查子进程是否结束
                if not process.is_alive():
                    # 进程自然结束，尝试获取结果
                    if not queue.empty():
                        self.solver_result = queue.get()
                    break
                
                # 检查队列是否有结果 (极端情况下进程还没死但结果已出)
                if not queue.empty():
                    self.solver_result = queue.get()
                    process.terminate() # 拿到结果后确保清理进程
                    break
                
                time.sleep(0.05) # 避免 CPU 占用过高
            except tk.TclError:
                # 窗口被手动关闭 (点击右上角 X)
                on_abort()
                return None

        # 清理 Tkinter 环境
        if not is_aborted:
            try:
                popup.destroy()
                root.destroy()
            except:
                pass

        return self.solver_result

    # --- 输入处理循环 ---
    
    def handle_input(self):
        """处理鼠标、键盘和窗口事件"""
        mx, my = pygame.mouse.get_pos()
        current_cls = ITEM_REGISTRY[self.selected_item_idx]
        hgx, hgy = self.screen_to_grid(mx, my, current_cls.placement_type)

        # 判断是否为简单放置类物品 (非数值、非方向、非连续工具)
        is_simple_batch = (not current_cls.has_number 
                           and not current_cls.has_direction 
                           and not current_cls.is_continuous_tool)

        # 1. UI 悬停状态更新
        for btn in self.buttons:
            btn.is_hovered = btn.rect.collidepoint((mx, my))

        for event in pygame.event.get():
            # A. 退出事件
            if event.type == pygame.QUIT:
                sys.exit()

            # B. 键盘事件 (修改数值/重置视图)
            elif event.type == pygame.KEYDOWN:
                 if event.key == pygame.K_r: self.cam_x, self.cam_y = 50, 50
                 if event.unicode.isdigit():
                    current_cls = ITEM_REGISTRY[self.selected_item_idx]
                    # 查找当前鼠标下支持数字的物品
                    candidates = [o for o in self.objects if o.gx == hgx and o.gy == hgy and o.has_number]
                    candidates.sort(key=lambda o: o.z_index, reverse=True)
                    if candidates:
                        # 修改最上层物品的数值
                        obj = candidates[0]
                        obj.data['num'] = int(event.unicode)
                        self.show_msg(f"数值设为 {event.unicode}")

            # C. 鼠标按下事件
            elif event.type == pygame.MOUSEBUTTONDOWN:
                current_cls = ITEM_REGISTRY[self.selected_item_idx]

                # --- 左键点击 ---
                if event.button == 1:
                    # 1. 检查UI点击
                    clicked_ui = False
                    for btn in self.buttons:
                        if btn.rect.collidepoint(event.pos):
                            # 处理功能按钮
                            if btn.data == "EXPORT": self.save_map()
                            elif btn.data == "IMPORT": self.load_map_from_file()
                            elif btn.data == "CLEAR": 
                                self.objects = []
                                self.cam_x, self.cam_y = 50, 50
                                self.show_msg("已重置")
                            elif btn.data == "WIPE":
                                # 仅清除 Solve_mode (线条/标记)
                                self.objects = [obj for obj in self.objects if not isinstance(obj, Solve_mode)]
                                self.show_msg("已清除所有连线/标记")
                            elif btn.data == "SOLVE":
                                # 调用异步求解器
                                solution_lines = self.run_async_solver("SOLVE")
                                
                                if solution_lines:
                                    # 加载解并转换为对象
                                    for item_data in solution_lines:
                                        new_obj = Solve_mode.from_dict(item_data)
                                        self.objects.append(new_obj)
                                    self.objects.sort(key=lambda o: o.z_index)
                                    self.show_msg(f"求解成功，生成 {len(solution_lines)} 条线")
                                elif solution_lines is not None:
                                    self.show_msg("未找到解")
                            elif btn.data == "DEDUCT":
                                # 调用异步推理逻辑
                                hints = self.run_async_solver("DEDUCT")
                                
                                if hints:
                                    # 将推理结果合并到盘面
                                    existing_signatures = set()
                                    for obj in self.objects:
                                        if obj.name == "Solve": 
                                            sig = (obj.gx, obj.gy, obj.data['dir'], obj.data['style'])
                                            existing_signatures.add(sig)
                                    
                                    count = 0
                                    for item in hints:
                                        sig = (item['x'], item['y'], item['data']['dir'], item['data']['style'])
                                        if sig not in existing_signatures:
                                            new_obj = Solve_mode.from_dict(item)
                                            self.place_object(new_obj) 
                                            count += 1
                                    self.show_msg(f"推理完成，新增 {count} 处标记")
                                elif hints is not None:
                                    self.show_msg("推理完成，没有发现新的确定项")
                            else: 
                                # 切换工具
                                self.selected_item_idx = btn.data
                            clicked_ui = True
                            break
                    if clicked_ui: continue

                    # 2. 初始化网格操作 (非UI区域)
                    self.is_dragging_action = True
                    self.drag_start_pos = event.pos
                    self.drag_start_grid = (hgx, hgy) 
                    self.last_drag_grid = (hgx, hgy)

                    # 简单批量模式：点击即放置
                    if is_simple_batch:
                        self.place_object(current_cls(hgx, hgy))
                    
                    # 连续工具模式：初始化状态
                    if current_cls.is_continuous_tool:
                        self.last_drag_grid = (hgx, hgy)
                        self.edge_op_mode = None

                # --- 中键点击 (平移) ---
                elif event.button == 2:
                    self.is_panning = True
                    self.last_mouse_pos = event.pos
                
                # --- 右键点击 (删除/特殊操作) ---
                elif event.button == 3:
                    if current_cls.is_continuous_tool:
                        # 连续工具的右键也是操作起始 (通常是反向操作，如画叉)
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        self.edge_op_mode = None
                    elif is_simple_batch:
                        # 简单物品批量删除
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        self.remove_object_at(hgx, hgy, target_layer_id=current_cls.layer_id)
                    else:
                        # 普通物品单点删除
                        self.remove_object_at(hgx, hgy, target_layer_id=current_cls.layer_id)

            # D. 鼠标释放事件
            elif event.type == pygame.MOUSEBUTTONUP:
                current_cls = ITEM_REGISTRY[self.selected_item_idx]
                
                # 处理复杂物品的放置 (需要在鼠标松开时确定方向或结束位置)
                if event.button == 1 and self.is_dragging_action and not current_cls.is_continuous_tool and not is_simple_batch:
                    if not any(b.rect.collidepoint(event.pos) for b in self.buttons):
                        start_gx, start_gy = self.drag_start_grid
                        new_obj = current_cls(start_gx, start_gy)
                        
                        # 调用物品配置回调 (如计算箭头方向)
                        new_obj.configure_on_creation(self.drag_start_pos, event.pos)
                        
                        self.place_object(new_obj)

                # 重置状态
                self.is_dragging_action = False
                self.edge_op_mode = None
                self.last_drag_grid = None
                if event.button == 2: self.is_panning = False

            # E. 鼠标移动事件
            elif event.type == pygame.MOUSEMOTION:
                # 视图平移
                if self.is_panning:
                    self.cam_x += event.pos[0] - self.last_mouse_pos[0]
                    self.cam_y += event.pos[1] - self.last_mouse_pos[1]
                    self.last_mouse_pos = event.pos

                # 拖拽操作逻辑
                if self.is_dragging_action:
                    # 1. 连续工具 (如画线)
                    if current_cls.is_continuous_tool:
                        self.handle_continuous_tool(hgx, hgy, current_cls)
                    
                    # 2. 简单批量工具 (如连续铺地板)
                    elif is_simple_batch:
                        if (hgx, hgy) != self.last_drag_grid:
                            is_left = pygame.mouse.get_pressed()[0]
                            is_right = pygame.mouse.get_pressed()[2]
                            
                            if is_left:
                                self.place_object(current_cls(hgx, hgy))
                            elif is_right:
                                self.remove_object_at(hgx, hgy, target_layer_id=current_cls.layer_id)
                            
                            self.last_drag_grid = (hgx, hgy)

    def handle_continuous_tool(self, curr_gx, curr_gy, tool_cls):
        """
        处理连续拖拽工具的逻辑 (边缘检测)
        根据鼠标从一个格子移动到相邻格子的动作，自动生成连接线或叉。
        """
        prev_gx, prev_gy = self.last_drag_grid
        if (curr_gx, curr_gy) == (prev_gx, prev_gy):
            return

        # 1. 确定操作对象 (EdgeItem) 的位置和方向
        target_obj = None
        # 判定移动方向 (水平或垂直)
        if curr_gx == prev_gx + 1 and curr_gy == prev_gy:
            target_obj = tool_cls(prev_gx, prev_gy, 'right')
        elif curr_gx == prev_gx - 1 and curr_gy == prev_gy:
            target_obj = tool_cls(curr_gx, curr_gy, 'right')
        elif curr_gx == prev_gx and curr_gy == prev_gy + 1:
            target_obj = tool_cls(prev_gx, prev_gy, 'down')
        elif curr_gx == prev_gx and curr_gy == prev_gy - 1:
            target_obj = tool_cls(curr_gx, curr_gy, 'down')
        
        if target_obj:
            # 2. 检查现有物品状态
            existing = None
            for obj in self.objects:
                if obj.gx == target_obj.gx and obj.gy == target_obj.gy and obj.layer_id == target_obj.layer_id:
                    existing = obj
                    break
            
            # 3. 确定操作模式 (仅在当前拖拽动作的第一次移动时确定，后续保持一致)
            is_right_btn = pygame.mouse.get_pressed()[2]
            if self.edge_op_mode is None:
                if is_right_btn:
                    # 右键逻辑: 如果有点叉则删叉，否则画叉
                    if existing and existing.data.get('style') == 'cross':
                        self.edge_op_mode = 'del_cross'
                    else:
                        self.edge_op_mode = 'draw_cross'
                else:
                    # 左键逻辑: 如果有线则删线，否则画线
                    if existing and existing.data.get('style') == 'line':
                        self.edge_op_mode = 'del_line'
                    else:
                        self.edge_op_mode = 'draw_line'

            # 4. 执行具体增删操作
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
        """主渲染循环"""
        self.screen.fill(BG_COLOR)
        
        # 1. 绘制所有物品
        for obj in self.objects:
            sx, sy = self.grid_to_screen(obj.gx, obj.gy)
            # 简单视锥剔除优化 (Off-screen culling)
            if -CELL_SIZE < sx < SCREEN_WIDTH and -CELL_SIZE < sy < SCREEN_HEIGHT:
                obj.draw(self.screen, self.cam_x, self.cam_y)

        # 2. 绘制幽灵光标 (预览位置)
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
            # 'edge' 工具通常通过格点或格内光标暗示

        # 3. 绘制拖拽辅助线 (针对有方向的物品)
        current_cls = ITEM_REGISTRY[self.selected_item_idx]
        if self.is_dragging_action and current_cls.has_direction:
             pygame.draw.line(self.screen, (255, 255, 0), self.drag_start_pos, pygame.mouse.get_pos(), 2)

        # 4. 绘制 UI 按钮
        for btn in self.buttons:
            is_sel = (btn.data == self.selected_item_idx)
            btn.draw(self.screen, is_sel)
            
        # 5. 绘制临时消息
        if time.time() < self.msg_timer:
            s = self.font.render(self.message, True, (0, 255, 0))
            self.screen.blit(s, (10, SCREEN_HEIGHT - 30))

        pygame.display.flip()

    def run(self):
        """程序主入口循环"""
        while True:
            self.handle_input()
            self.draw()
            self.clock.tick(60)

if __name__ == "__main__":
    GridEditor().run()