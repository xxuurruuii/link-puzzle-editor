# editor.py
# 网格谜题编辑器 - 主控制器
# 负责：UI渲染与交互、输入事件处理、视图变换、求解器调度

import pygame
import sys
import time
import multiprocessing
import tkinter as tk
import tkinter.ttk as ttk

# --- 本地模块导入 ---
from config import *
from ui import Button
from map_objects import ITEM_REGISTRY, Solve_mode
from worker import solver_worker
from io_handler import save_map_to_json, load_map_from_json
import actions
import renderer

class GridEditor:
    """
    编辑器主类
    管理整个应用程序的生命周期、状态和输入分发
    """
    def __init__(self):
        # --- 1. Pygame 初始化 ---
        pygame.init()
        # 启用可调整大小的窗口
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("网格编辑器")
        self.clock = pygame.time.Clock()
        
        # 字体加载逻辑：尝试加载系统字体，失败则回退到默认字体
        f_path = pygame.font.match_font('simhei,microsoftyahei,arial')
        self.font = pygame.font.Font(f_path, 16) if f_path else pygame.font.SysFont('arial', 16)

        # --- 2. 核心数据状态 ---
        self.objects = []               # 存储盘面上的所有对象实例
        self.cam_x, self.cam_y = 50, 50 # 摄像机（视口）偏移量
        self.cell_size = DEFAULT_CELL_SIZE # 当前网格大小（支持缩放）
        
        # --- 3. 交互状态标志 ---
        self.selected_item_idx = 0      # 当前选中的工具/物品索引
        self.is_panning = False         # 是否正在按住中键平移
        self.is_dragging_action = False # 是否正在进行拖拽操作（如批量放置、画线）
        self.drag_start_pos = (0, 0)    # 拖拽开始时的屏幕坐标
        self.last_mouse_pos = (0, 0)    # 上一帧鼠标位置（用于计算平移差值）

        # --- 4. 工具特定状态 ---
        self.last_drag_grid = None      # 上一次操作的网格坐标（防止重复操作）
        self.edge_op_mode = None        # 边缘工具模式（如：正在画线还是正在擦除）
        self.message = ""               # 底部提示消息内容
        self.msg_timer = 0              # 提示消息消失时间戳
        
        # --- 5. UI 布局状态 ---
        self.current_tab = 0            # 当前激活的标签页索引
        self.tab_buttons = []           # 顶部的标签切换按钮
        # 页面内容容器：{页码: [按钮列表]}
        self.pages = {0: [], 1: [], 2: [], 3: []}
        
        # 初始化 UI
        self.setup_ui()

    def setup_ui(self):
        """初始化界面布局，创建标签页和功能按钮"""
        
        # --- 1. 创建顶部标签切换按钮 ---
        tab_names = ["系统", "普通", "数字", "顶点"]
        base_x = UI_MARGIN
        base_y = UI_MARGIN
        
        for i, name in enumerate(tab_names):
            # 计算每个标签的位置
            x = base_x + i * (TAB_WIDTH + UI_GAP)
            # data 设置为 "TAB_0" 格式，方便在点击事件中解析
            btn = Button(x, base_y, TAB_WIDTH, TAB_HEIGHT, name, self.font, f"TAB_{i}")
            self.tab_buttons.append(btn)

        # --- 2. 准备内容按钮的布局参数 ---
        content_x = UI_MARGIN
        # 内容按钮起始 Y 坐标 = 边距 + 标签高度 + 间隙
        content_y_start = UI_MARGIN + TAB_HEIGHT + UI_GAP

        # 辅助函数：向指定页添加按钮并自动更新 Y 坐标
        def add_btn(page_idx, text, callback_data, current_y):
            btn = Button(content_x, current_y, BTN_WIDTH, BTN_HEIGHT, text, self.font, callback_data)
            self.pages[page_idx].append(btn)
            return current_y + BTN_HEIGHT + UI_GAP

        # --- 3. 填充第0页：系统功能 ---
        y = content_y_start
        
        # 3.1 特殊处理：将"试解(Solve_mode)"工具放在系统页
        solve_tool = next((i for i, c in enumerate(ITEM_REGISTRY) if c == Solve_mode), None)
        if solve_tool is not None:
             y = add_btn(0, "试解", solve_tool, y)
             
        # 3.2 添加系统功能按钮
        funcs = [("清空", "WIPE"), ("!重置", "CLEAR"), ("LOAD", "IMPORT"), 
                 ("SAVE", "EXPORT"), ("SOLVE", "SOLVE"), ("DEDUCT", "DEDUCT")]
        for text, action in funcs:
            y = add_btn(0, text, action, y)

        # --- 4. 填充第1-3页：根据物品属性自动分类 ---
        y1 = content_y_start # 普通物件 (Page 1)
        y2 = content_y_start # 数字物件 (Page 2)
        y3 = content_y_start # 格点物件 (Page 3)

        for idx, cls in enumerate(ITEM_REGISTRY):
            if cls == Solve_mode: continue # 跳过已处理的试解工具
            
            # 根据 placement_type 和 has_number 进行分类
            if cls.placement_type == 'vertex':
                # Page 3: 格点物件 (如 Slitherlink)
                y3 = add_btn(3, cls.name, idx, y3)
            elif cls.placement_type == 'cell':
                if cls.has_number:
                    # Page 2: 格子中心含数字 (如 EndPoint, Yajilin)
                    y2 = add_btn(2, cls.name, idx, y2)
                else:
                    # Page 1: 格子中心不含数字 (如 Floor, Wall)
                    y1 = add_btn(1, cls.name, idx, y1)
            else:
                # 其他类型默认放入普通页
                y1 = add_btn(1, cls.name, idx, y1)

    # ----------------------------
    #       坐标转换 (View Core)
    # ----------------------------
    def screen_to_grid(self, sx, sy, mode='cell'):
        """
        屏幕像素坐标 -> 网格逻辑坐标
        :param mode: 'cell'(取整到格子内部) 或 'vertex'(四舍五入到最近格点)
        """
        if mode == 'vertex':
            gx = round((sx - self.cam_x) / self.cell_size)
            gy = round((sy - self.cam_y) / self.cell_size)
            return int(gx), int(gy)
        # 默认 cell 模式向下取整
        return int((sx - self.cam_x) // self.cell_size), int((sy - self.cam_y) // self.cell_size)

    def grid_to_screen(self, gx, gy):
        """网格逻辑坐标 -> 屏幕像素坐标"""
        return gx * self.cell_size + self.cam_x, gy * self.cell_size + self.cam_y

    def show_msg(self, text):
        """在屏幕底部显示临时消息"""
        self.message = text
        self.msg_timer = time.time() + 2

    # ----------------------------
    #       求解器控制 (Solver)
    # ----------------------------
    def run_async_solver(self, mode):
        """
        启动后台进程运行求解器，并显示 Tkinter 加载弹窗
        :param mode: 'SOLVE' (求一解) 或 'DEDUCT' (推演)
        """
        # 序列化当前数据
        current_data = [obj.to_dict() for obj in self.objects]
        queue = multiprocessing.Queue()
        
        # 启动子进程
        process = multiprocessing.Process(target=solver_worker, args=(mode, current_data, queue))
        process.start()
        
        # 创建 Tkinter 弹窗 (隐藏主窗口，只显示弹窗)
        root = tk.Tk()
        root.withdraw()
        popup = tk.Toplevel(root)
        popup.title("计算中...")
        
        # 弹窗居中
        x = (root.winfo_screenwidth() // 2) - 150
        y = (root.winfo_screenheight() // 2) - 60
        popup.geometry(f"300x120+{int(x)}+{int(y)}")
        popup.grab_set() # 模态窗口
        popup.resizable(False, False)

        tk.Label(popup, text=f"运行 {mode} 中...\n(请稍候)", pady=20).pack()
        self.solver_result = None
        is_aborted = False

        # 中止回调
        def on_abort():
            nonlocal is_aborted
            is_aborted = True
            if process.is_alive():
                process.terminate() # 强制结束子进程
                process.join()
            popup.destroy()
            root.destroy()
            self.show_msg("已中止")

        ttk.Button(popup, text="中止", command=on_abort).pack(pady=5)

        # 轮询检查子进程状态
        while True:
            try:
                popup.update()
                popup.update_idletasks()
                # 如果进程结束或队列有数据
                if not process.is_alive() or not queue.empty():
                    if not queue.empty(): self.solver_result = queue.get()
                    if process.is_alive(): process.terminate()
                    break
                time.sleep(0.05)
            except tk.TclError: # 处理窗口意外关闭
                on_abort()
                return None
        
        if not is_aborted:
            try:
                popup.destroy()
                root.destroy()
            except: pass
        return self.solver_result

    # ----------------------------
    #       事件分发 (Input Loop)
    # ----------------------------
    def handle_input(self):
        """处理每一帧的用户输入（鼠标、键盘、系统事件）"""
        mx, my = pygame.mouse.get_pos()
        current_cls = ITEM_REGISTRY[self.selected_item_idx]
        
        # 计算鼠标下的网格坐标
        hgx, hgy = self.screen_to_grid(mx, my, current_cls.placement_type)

        # 判断是否为简单点击放置的物品（非数字、非方向、非连续工具）
        is_simple_batch = (not current_cls.has_number 
                           and not current_cls.has_direction 
                           and not current_cls.is_continuous_tool)

        # 1. 更新 UI 按钮的悬停状态
        # 只检测当前可见的按钮（标签 + 当前页内容）
        visible_buttons = self.tab_buttons + self.pages[self.current_tab]
        for btn in visible_buttons:
            btn.is_hovered = btn.rect.collidepoint((mx, my))

        # 2. Pygame 事件循环
        for event in pygame.event.get():
            # --- 退出事件 ---
            if event.type == pygame.QUIT:
                sys.exit()

            # --- 窗口调整事件 ---
            elif event.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)

            # --- 滚轮缩放事件 ---
            elif event.type == pygame.MOUSEWHEEL:
                # 定点缩放逻辑：
                # 1. 计算鼠标相对于网格原点的偏移比例
                offset_x = (mx - self.cam_x) / self.cell_size
                offset_y = (my - self.cam_y) / self.cell_size
                
                # 2. 计算新尺寸 (限制在 10-200 像素之间)
                change = event.y * 10 
                new_size = max(10, min(200, self.cell_size + change))
                
                # 3. 反推新的 cam_x/y，保持鼠标下的网格点位置不变
                if new_size != self.cell_size:
                    self.cell_size = new_size
                    self.cam_x = mx - offset_x * self.cell_size
                    self.cam_y = my - offset_y * self.cell_size

            # --- 键盘事件 ---
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r: self.cam_x, self.cam_y = 50, 50 # 重置视图
                
                # 处理数字输入 (修改鼠标下物品的数值)
                if event.unicode.isdigit():
                    candidates = [
                        o for o in self.objects 
                        if o.gx == hgx and o.gy == hgy and o.has_number and isinstance(o, current_cls)
                    ]
                    candidates.sort(key=lambda o: o.z_index, reverse=True) # 优先修改最上层的
                    if candidates:
                        obj = candidates[0]
                        digit = int(event.unicode)
                        current_val = obj.data.get('num', 0)
                        limit = getattr(obj, 'num_limit', 10)
                        
                        # 逻辑：拼接数字，若超限则重置为新输入的单个数字
                        new_val = current_val * 10 + digit
                        if new_val >= limit:
                            new_val = digit
                        
                        obj.data['num'] = new_val
                        
                # 空格键清零
                if event.key == pygame.K_SPACE:
                    candidates = [
                        o for o in self.objects 
                        if o.gx == hgx and o.gy == hgy and o.has_number and isinstance(o, current_cls)
                    ]
                    candidates.sort(key=lambda o: o.z_index, reverse=True)
                    if candidates:
                        candidates[0].data['num'] = 0

            # --- 鼠标按下事件 ---
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # 左键 (Button 1)
                if event.button == 1: 
                    # 3.1 优先处理 UI 点击
                    clicked_ui = False
                    
                    # A. 检查顶部标签
                    for btn in self.tab_buttons:
                        if btn.rect.collidepoint(event.pos):
                            self.current_tab = int(btn.data.split('_')[1])
                            clicked_ui = True
                            break
                    
                    # B. 检查页面内容按钮
                    if not clicked_ui:
                        active_buttons = self.pages[self.current_tab]
                        for btn in active_buttons:
                            if btn.rect.collidepoint(event.pos):
                                # 处理功能按钮逻辑
                                if btn.data == "EXPORT": 
                                    _, msg = save_map_to_json(self.objects)
                                    self.show_msg(msg)
                                elif btn.data == "IMPORT": 
                                    new_objs, msg = load_map_from_json()
                                    if new_objs is not None: 
                                        self.objects = new_objs
                                        self.objects.sort(key=lambda o: o.z_index)
                                    self.show_msg(msg)
                                elif btn.data == "CLEAR": 
                                    self.objects = []
                                    self.show_msg("已重置")
                                elif btn.data == "WIPE":
                                    self.objects = [obj for obj in self.objects if not isinstance(obj, Solve_mode)]
                                    self.show_msg("已清除标记")
                                elif btn.data == "SOLVE":
                                    res = self.run_async_solver("SOLVE")
                                    if res:
                                        # 将结果添加进盘面
                                        for d in res: self.objects.append(Solve_mode.from_dict(d))
                                        self.objects.sort(key=lambda o: o.z_index)
                                        self.show_msg(f"生成 {len(res)} 条线")
                                    elif res is not None: self.show_msg("无解")
                                elif btn.data == "DEDUCT":
                                    res = self.run_async_solver("DEDUCT")
                                    if res:
                                        # 过滤已存在的标记，只添加新的
                                        sigs = {(o.gx, o.gy, o.data['dir'], o.data['style']) for o in self.objects if o.name == "TrySolve"}
                                        cnt = 0
                                        for d in res:
                                            sig = (d['x'], d['y'], d['data']['dir'], d['data']['style'])
                                            if sig not in sigs:
                                                actions.place_object(self, Solve_mode.from_dict(d))
                                                cnt += 1
                                        self.show_msg(f"新增 {cnt} 处标记")
                                    elif res is not None: self.show_msg("无新推论")
                                else: 
                                    # 切换选中的物品工具
                                    self.selected_item_idx = btn.data
                                clicked_ui = True
                                break
                    if clicked_ui: continue

                    # 3.2 处理网格交互 (开始放置/拖拽)
                    self.is_dragging_action = True
                    self.drag_start_pos = event.pos
                    self.drag_start_grid = (hgx, hgy) 
                    self.last_drag_grid = (hgx, hgy)

                    # 立即放置简单物品
                    if is_simple_batch:
                        actions.place_object(self, current_cls(hgx, hgy))
                    
                    # 重置边缘工具模式 (画线/擦除在第一次拖拽时确定)
                    if current_cls.is_continuous_tool:
                        self.edge_op_mode = None

                # 中键 (Button 2): 平移
                elif event.button == 2: 
                    self.is_panning = True
                    self.last_mouse_pos = event.pos
                
                # 右键 (Button 3): 删除或反向操作
                elif event.button == 3: 
                    if current_cls.is_continuous_tool:
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        self.edge_op_mode = None
                    elif is_simple_batch:
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        actions.remove_object_at(self, hgx, hgy, current_cls.layer_id)
                    else:
                        # 单次点击删除
                        actions.remove_object_at(self, hgx, hgy, current_cls.layer_id)

            # --- 鼠标松开事件 ---
            elif event.type == pygame.MOUSEBUTTONUP:
                # 左键松开：完成复杂物品的放置 (如带方向的箭头)
                if event.button == 1 and self.is_dragging_action and not current_cls.is_continuous_tool and not is_simple_batch:
                    # 确保没有在 UI 上释放
                    visible_buttons = self.tab_buttons + self.pages[self.current_tab]
                    if not any(b.rect.collidepoint(event.pos) for b in visible_buttons):
                        new_obj = current_cls(self.drag_start_grid[0], self.drag_start_grid[1])
                        # 根据拖拽的起止点配置对象 (例如确定方向)
                        new_obj.configure_on_creation(self.drag_start_pos, event.pos)
                        actions.place_object(self, new_obj)

                # 重置状态
                self.is_dragging_action = False
                self.edge_op_mode = None
                self.last_drag_grid = None
                if event.button == 2: self.is_panning = False

            # --- 鼠标移动事件 ---
            elif event.type == pygame.MOUSEMOTION:
                # 处理平移
                if self.is_panning:
                    self.cam_x += event.pos[0] - self.last_mouse_pos[0]
                    self.cam_y += event.pos[1] - self.last_mouse_pos[1]
                    self.last_mouse_pos = event.pos

                # 处理拖拽操作
                if self.is_dragging_action:
                    if current_cls.is_continuous_tool:
                        # 委托给 actions 模块处理连续画线/画叉
                        actions.handle_continuous_tool(self, hgx, hgy, current_cls)
                    elif is_simple_batch:
                        # 简单的批量涂抹 (按住左键画，按住右键擦)
                        if (hgx, hgy) != self.last_drag_grid:
                            if pygame.mouse.get_pressed()[0]:
                                actions.place_object(self, current_cls(hgx, hgy))
                            elif pygame.mouse.get_pressed()[2]:
                                actions.remove_object_at(self, hgx, hgy, current_cls.layer_id)
                            self.last_drag_grid = (hgx, hgy)

    def run(self):
        """主循环"""
        while True:
            self.handle_input()
            renderer.render_scene(self)
            self.clock.tick(60) # 限制 60 FPS