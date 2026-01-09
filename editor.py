# editor.py
import pygame
import sys
import time
import multiprocessing
import tkinter as tk
import tkinter.ttk as ttk

from config import *
from ui import Button
from map_objects import ITEM_REGISTRY, Solve_mode
from worker import solver_worker
from io_handler import save_map_to_json, load_map_from_json

import actions
import renderer

class GridEditor:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("网格编辑器")
        self.clock = pygame.time.Clock()
        
        f_path = pygame.font.match_font('simhei,microsoftyahei,arial')
        self.font = pygame.font.Font(f_path, 16) if f_path else pygame.font.SysFont('arial', 16)

        # 核心状态数据
        self.objects = [] 
        self.cam_x, self.cam_y = 50, 50
        
        # 交互状态
        self.selected_item_idx = 0 
        self.is_panning = False
        self.is_dragging_action = False
        self.drag_start_pos = (0,0)
        self.last_mouse_pos = (0,0)

        # 工具状态
        self.last_drag_grid = None  
        self.edge_op_mode = None    
        self.message = ""
        self.msg_timer = 0
        
        self.buttons = []
        self.setup_ui()

    def setup_ui(self):
        x, y, w, h, gap = 10, 10, 100, 35, 5
        # 物品按钮
        for idx, cls in enumerate(ITEM_REGISTRY):
            self.buttons.append(Button(x, y, w, h, cls.name, self.font, idx))
            y += h + gap
        # 功能按钮
        funcs = [("清空", "WIPE"), ("!重置", "CLEAR"), ("LOAD", "IMPORT"), ("SAVE", "EXPORT"), ("SOLVE_ONE", "SOLVE"), ("DEDUCT", "DEDUCT")]
        for text, action in funcs:
            self.buttons.append(Button(x, y, w, h, text, self.font, action))
            y += h + gap

    # --- 坐标转换工具 (View Core) ---
    def screen_to_grid(self, sx, sy, mode='cell'):
        if mode == 'vertex':
            gx = round((sx - self.cam_x) / CELL_SIZE)
            gy = round((sy - self.cam_y) / CELL_SIZE)
            return int(gx), int(gy)
        return (sx - self.cam_x) // CELL_SIZE, (sy - self.cam_y) // CELL_SIZE

    def grid_to_screen(self, gx, gy):
        return gx * CELL_SIZE + self.cam_x, gy * CELL_SIZE + self.cam_y

    def show_msg(self, text):
        self.message = text
        self.msg_timer = time.time() + 2

    # --- 异步求解逻辑 (Solver Control) ---
    def run_async_solver(self, mode):
        current_data = [obj.to_dict() for obj in self.objects]
        queue = multiprocessing.Queue()
        process = multiprocessing.Process(target=solver_worker, args=(mode, current_data, queue))
        process.start()
        
        root = tk.Tk()
        root.withdraw()
        popup = tk.Toplevel(root)
        popup.title("计算中...")
        x = (root.winfo_screenwidth() // 2) - 150
        y = (root.winfo_screenheight() // 2) - 60
        popup.geometry(f"300x120+{int(x)}+{int(y)}")
        popup.grab_set()
        popup.resizable(False, False)

        tk.Label(popup, text=f"运行 {mode} 中...\n(请稍候)", pady=20).pack()
        self.solver_result = None
        is_aborted = False

        def on_abort():
            nonlocal is_aborted
            is_aborted = True
            if process.is_alive():
                process.terminate()
                process.join()
            popup.destroy()
            root.destroy()
            self.show_msg("已中止")

        ttk.Button(popup, text="中止", command=on_abort).pack(pady=5)

        while True:
            try:
                popup.update()
                popup.update_idletasks()
                if not process.is_alive() or not queue.empty():
                    if not queue.empty(): self.solver_result = queue.get()
                    if process.is_alive(): process.terminate()
                    break
                time.sleep(0.05)
            except tk.TclError:
                on_abort()
                return None
        
        if not is_aborted:
            try:
                popup.destroy()
                root.destroy()
            except: pass
        return self.solver_result

    # --- 主输入循环 (Event Dispatcher) ---
    def handle_input(self):
        mx, my = pygame.mouse.get_pos()
        current_cls = ITEM_REGISTRY[self.selected_item_idx]
        hgx, hgy = self.screen_to_grid(mx, my, current_cls.placement_type)

        is_simple_batch = (not current_cls.has_number 
                           and not current_cls.has_direction 
                           and not current_cls.is_continuous_tool)

        # 更新按钮悬停
        for btn in self.buttons:
            btn.is_hovered = btn.rect.collidepoint((mx, my))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                sys.exit()

            # 键盘: 快捷键与数值修改
            elif event.type == pygame.KEYDOWN:
                 if event.key == pygame.K_r: self.cam_x, self.cam_y = 50, 50
                 if event.unicode.isdigit():
                    candidates = [
                        o for o in self.objects 
                        if o.gx == hgx and o.gy == hgy and o.has_number and isinstance(o, current_cls)
                    ]
                    candidates.sort(key=lambda o: o.z_index, reverse=True)
                    if candidates:
                        candidates[0].data['num'] = int(event.unicode)
                        self.show_msg(f"数值设为 {event.unicode}")

            # 鼠标按下
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1: # 左键
                    # 1. 处理 UI 点击
                    clicked_ui = False
                    for btn in self.buttons:
                        if btn.rect.collidepoint(event.pos):
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
                                    for d in res: self.objects.append(Solve_mode.from_dict(d))
                                    self.objects.sort(key=lambda o: o.z_index)
                                    self.show_msg(f"生成 {len(res)} 条线")
                                elif res is not None: self.show_msg("无解")
                            elif btn.data == "DEDUCT":
                                res = self.run_async_solver("DEDUCT")
                                if res:
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
                                self.selected_item_idx = btn.data
                            clicked_ui = True
                            break
                    if clicked_ui: continue

                    # 2. 处理网格操作
                    self.is_dragging_action = True
                    self.drag_start_pos = event.pos
                    self.drag_start_grid = (hgx, hgy) 
                    self.last_drag_grid = (hgx, hgy)

                    if is_simple_batch:
                        actions.place_object(self, current_cls(hgx, hgy))
                    
                    if current_cls.is_continuous_tool:
                        self.edge_op_mode = None

                elif event.button == 2: # 中键平移
                    self.is_panning = True
                    self.last_mouse_pos = event.pos
                
                elif event.button == 3: # 右键删除/反向操作
                    if current_cls.is_continuous_tool:
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        self.edge_op_mode = None
                    elif is_simple_batch:
                        self.is_dragging_action = True
                        self.last_drag_grid = (hgx, hgy)
                        actions.remove_object_at(self, hgx, hgy, current_cls.layer_id)
                    else:
                        actions.remove_object_at(self, hgx, hgy, current_cls.layer_id)

            # 鼠标释放
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1 and self.is_dragging_action and not current_cls.is_continuous_tool and not is_simple_batch:
                    if not any(b.rect.collidepoint(event.pos) for b in self.buttons):
                        new_obj = current_cls(self.drag_start_grid[0], self.drag_start_grid[1])
                        new_obj.configure_on_creation(self.drag_start_pos, event.pos)
                        actions.place_object(self, new_obj)

                self.is_dragging_action = False
                self.edge_op_mode = None
                self.last_drag_grid = None
                if event.button == 2: self.is_panning = False

            # 鼠标移动
            elif event.type == pygame.MOUSEMOTION:
                if self.is_panning:
                    self.cam_x += event.pos[0] - self.last_mouse_pos[0]
                    self.cam_y += event.pos[1] - self.last_mouse_pos[1]
                    self.last_mouse_pos = event.pos

                if self.is_dragging_action:
                    if current_cls.is_continuous_tool:
                        # 委托给 actions 模块处理
                        actions.handle_continuous_tool(self, hgx, hgy, current_cls)
                    elif is_simple_batch:
                        if (hgx, hgy) != self.last_drag_grid:
                            if pygame.mouse.get_pressed()[0]:
                                actions.place_object(self, current_cls(hgx, hgy))
                            elif pygame.mouse.get_pressed()[2]:
                                actions.remove_object_at(self, hgx, hgy, current_cls.layer_id)
                            self.last_drag_grid = (hgx, hgy)

    def run(self):
        while True:
            self.handle_input()
            # 委托给 renderer 模块绘制
            renderer.render_scene(self)
            self.clock.tick(60)