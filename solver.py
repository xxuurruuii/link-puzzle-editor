# solver.py
# 基于 cspuz 库的网格谜题求解逻辑核心
# 负责构建数学约束模型，并执行求解或逻辑推演

import sys
from collections import defaultdict
from cspuz.solver import Solver
from cspuz.graph import Graph, active_edges_acyclic
from cspuz.constraints import count_true

# --- 内部函数：模型构建 ---
def _build_model(problem_data):
    """
    根据传入的盘面数据构建 cspuz 约束模型。
    
    :param problem_data: 包含所有盘面对象的列表
    :return: 包含求解器实例、变量句柄及网格信息的上下文字典
    """
    objects = problem_data
    if not objects:
        return None

    # 1. 计算网格边界
    xs = [obj['x'] for obj in objects]
    ys = [obj['y'] for obj in objects]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    # 2. 数据分类与映射
    # 将对象分类存储，方便后续应用约束
    valid_cells = set()   # 有效路面 (地板、端点、白圆等)
    endpoints = {}        # 端点 {pos: number}
    simpleloops = set()   # Simpleloop 线索位置
    slitherlinks = []     # Slitherlink 对象列表 (位于格点)
    walls = set()         # 墙壁位置
    masyu_w = set()       # Masyu 白圆位置
    masyu_b = set()       # Masyu 黑圆位置
    
    max_num = 0

    for obj in objects:
        # 将全局坐标转换为局部网格坐标 (row, col)
        lx = obj['x'] - min_x
        ly = obj['y'] - min_y
        pos = (ly, lx) 
        t = obj['type']
        
        if t == 'FloorCell':
            valid_cells.add(pos)
        elif t == 'Simpleloop':
            simpleloops.add(pos)
        elif t == 'Wall':
            walls.add(pos)
        elif t == 'EndPoint':
            valid_cells.add(pos)
            num = obj.get('data', {}).get('num', 0)
            if num > 0:
                endpoints[pos] = num
                max_num = max(max_num, num)
        elif t == 'Slitherlink':
            slitherlinks.append(obj)
        elif t == 'MasyuW':
            masyu_w.add(pos)
        elif t == 'MasyuB':
            masyu_b.add(pos)

    # 3. 初始化求解器
    solver = Solver()

    # 4. 定义核心变量
    # path_id: 每个格子的线路编号 (0表示空，>0表示属于某条线路)
    path_id = solver.int_array((height, width), 0, max_num)
    
    # h_edges: 横向边变量 (y, x) -- (y, x+1)
    h_edges = solver.bool_array((height, width - 1))
    # v_edges: 纵向边变量 (y, x) -- (y+1, x)
    v_edges = solver.bool_array((height - 1, width))

    # 5. 应用现有盘面标记 (用户已画的线/叉)
    for obj in objects:
        if obj['type'] == 'Solve_mode':
            lx = obj['x'] - min_x
            ly = obj['y'] - min_y
            
            d = obj.get('data', {})
            direction = d.get('dir', 'right')
            style = d.get('style', 'line')
            
            # 横向标记
            if direction == 'right':
                if 0 <= ly < height and 0 <= lx < width - 1:
                    edge = h_edges[ly, lx]
                    if style == 'line':
                        solver.ensure(edge)        # 强制有线
                    elif style == 'cross':
                        solver.ensure(~edge)       # 强制无线 (cspuz 取反)
                        
            # 纵向标记
            elif direction == 'down':
                if 0 <= ly < height - 1 and 0 <= lx < width:
                    edge = v_edges[ly, lx]
                    if style == 'line':
                        solver.ensure(edge)
                    elif style == 'cross':
                        solver.ensure(~edge)

    # 6. 构建图结构与连通性约束
    graph = Graph(height * width)
    all_active_edges = []

    # 添加横向边及流约束
    for y in range(height):
        for x in range(width - 1):
            u = y * width + x
            v = y * width + (x + 1)
            graph.add_edge(u, v)
            all_active_edges.append(h_edges[y, x])
            # 流约束：若边连通，则两侧 path_id 必须相同
            solver.ensure(h_edges[y, x].then(path_id[y, x] == path_id[y, x + 1]))

    # 添加纵向边及流约束
    for y in range(height - 1):
        for x in range(width):
            u = y * width + x
            v = (y + 1) * width + x
            graph.add_edge(u, v)
            all_active_edges.append(v_edges[y, x])
            # 流约束：若边连通，则两侧 path_id 必须相同
            solver.ensure(v_edges[y, x].then(path_id[y, x] == path_id[y + 1, x]))

    # --- 辅助函数：Masyu 逻辑专用 ---
    # neg 参数用于处理边界外的取反逻辑，避免直接对 False 取反导致崩溃
    def get_h(r, c, neg=False):
        if 0 <= r < height and 0 <= c < width - 1:
            val = h_edges[r, c]
            return ~val if neg else val
        return neg 

    def get_v(r, c, neg=False):
        if 0 <= r < height - 1 and 0 <= c < width:
            val = v_edges[r, c]
            return ~val if neg else val
        return neg 

    # A. 全局约束：无环 (Numberlink 基础)
    active_edges_acyclic(solver, all_active_edges, graph)

    # B. 单元格局部约束 (叠加式处理)
    for y in range(height):
        for x in range(width):
            pos = (y, x)
            
            # 获取当前格子四周的边
            neighbors = []
            if x > 0: neighbors.append(h_edges[y, x - 1])         # 左
            if x < width - 1: neighbors.append(h_edges[y, x])     # 右
            if y > 0: neighbors.append(v_edges[y - 1, x])         # 上
            if y < height - 1: neighbors.append(v_edges[y, x])    # 下
            
            degree = count_true(neighbors)
            
            # 标记：当前格子是否受到特殊线索（仅端点，Wall和Ice）的约束
            is_constrained = False
            
            # (1) 端点约束
            if pos in endpoints:
                solver.ensure(degree == 1)
                solver.ensure(path_id[y, x] == endpoints[pos])
                is_constrained = True
            
            # (2) 墙壁约束
            if pos in walls:
                solver.ensure(degree == 0)
                solver.ensure(path_id[y, x] == 0)
                is_constrained = True
            
            # (3) Simpleloop 约束
            if pos in simpleloops:
                solver.ensure(degree >= 2)
                solver.ensure(path_id[y, x] != 0)
            
            # (4) Masyu 白圆约束
            if pos in masyu_w:
                # 必须经过
                solver.ensure(degree >= 2)
                solver.ensure(path_id[y, x] != 0)
                
                # 逻辑: 直行 且 两侧至少有一侧在下一格转弯
                l1 = get_h(y, x - 1)
                r1 = get_h(y, x)    
                u1 = get_v(y - 1, x)
                d1 = get_v(y, x)    
                
                # 获取延伸两格的边状态 (neg=True 用于检测断开)
                l2 = get_h(y, x - 2, neg=True)
                r2 = get_h(y, x + 1, neg=True)
                u2 = get_v(y - 2, x, neg=True)
                d2 = get_v(y + 1, x, neg=True)

                solver.ensure(l1 == r1)
                solver.ensure(u1 == d1)

                # 左邻格(y, x-1)是否有垂直边 / 右邻格(y, x+1)是否有垂直边
                v_at_l = get_v(y - 1, x - 1) | get_v(y, x - 1)
                v_at_r = get_v(y - 1, x + 1) | get_v(y, x + 1)
                
                # 上邻格(y-1, x)是否有水平边 / 下邻格(y+1, x)是否有水平边
                h_at_u = get_h(y - 1, x - 1) | get_h(y - 1, x)
                h_at_d = get_h(y + 1, x - 1) | get_h(y + 1, x)

                # 1. 如果横向有线 (l1为真)，则必须满足：(左侧转弯) 或 (右侧转弯)
                #    其中“侧转弯”定义为：无延伸 且 有垂直边
                h_condition = (l2 & v_at_l) | (r2 & v_at_r)
                if l1 is not False:
                    solver.ensure(l1.then(h_condition))

                # 2. 如果纵向有线 (u1为真)，则必须满足：(上侧转弯) 或 (下侧转弯)
                v_condition = (u2 & h_at_u) | (d2 & h_at_d)
                if u1 is not False:
                    solver.ensure(u1.then(v_condition))
                

            # (5) Masyu 黑圆约束
            if pos in masyu_b:
                # 必须经过
                solver.ensure(degree == 2)
                solver.ensure(path_id[y, x] != 0)

                # 逻辑: 必须转弯 且 两侧直线延伸至少两格
                valid_l = get_h(y, x - 1) & get_h(y, x - 2) # 左侧两格连通
                valid_r = get_h(y, x)     & get_h(y, x + 1) # 右侧两格连通
                valid_u = get_v(y - 1, x) & get_v(y - 2, x) # 上侧两格连通
                valid_d = get_v(y, x)     & get_v(y + 1, x) # 下侧两格连通
                
                # (横向有效 & 纵向有效) -> 意味着发生了转弯且延伸足够
                solver.ensure((valid_l | valid_r) & (valid_u | valid_d))

            # (6) 默认逻辑 (无特殊约束时)
            if not is_constrained:
                if pos in valid_cells:
                    # 地板：可以是通路(2)也可以是空(0)
                    solver.ensure((degree == 0) | (degree == 2))
                    solver.ensure((degree == 0) == (path_id[y, x] == 0))
                else:
                    # 空白区域：必须为空
                    solver.ensure(degree == 0)
                    solver.ensure(path_id[y, x] == 0)

    # C. Slitherlink 约束 (基于格点)
    for obj in slitherlinks:
        lx = obj['x'] - min_x
        ly = obj['y'] - min_y
        target_num = obj.get('data', {}).get('num', 0)
        
        # 获取顶点周围的四条边
        neighbors = []
        if 0 <= ly - 1 < height and 0 <= lx - 1 < width - 1:
            neighbors.append(h_edges[ly - 1, lx - 1]) # 上
        if 0 <= ly < height and 0 <= lx - 1 < width - 1:
            neighbors.append(h_edges[ly, lx - 1])     # 下
        if 0 <= ly - 1 < height - 1 and 0 <= lx - 1 < width:
            neighbors.append(v_edges[ly - 1, lx - 1]) # 左
        if 0 <= ly - 1 < height - 1 and 0 <= lx < width:
            neighbors.append(v_edges[ly - 1, lx])     # 右

        # 约束: 周围存在的边数量等于提示数字
        solver.ensure(count_true(neighbors) == target_num)

    # 7. 设置 Answer Key (关键)
    # 标记需要从求解结果中读取的变量
    solver.add_answer_key(path_id)
    solver.add_answer_key(h_edges)
    solver.add_answer_key(v_edges)

    return {
        "solver": solver,
        "h_edges": h_edges,
        "v_edges": v_edges,
        "min_x": min_x,
        "min_y": min_y,
        "width": width,
        "height": height,
        "valid_cells": valid_cells
    }

# --- 外部接口：求解 (获取单一解) ---
def solve(problem_data):
    ctx = _build_model(problem_data)
    if not ctx: return []

    solver = ctx["solver"]
    h_edges = ctx["h_edges"]
    v_edges = ctx["v_edges"]
    min_x, min_y = ctx["min_x"], ctx["min_y"]
    width, height = ctx["width"], ctx["height"]

    print("Solver (cspuz): 开始求解...")
    
    # 获取任意一个可行解
    if solver.find_answer():
        print("Solver (cspuz): 求解成功")
        solution_objects = []
        
        # 提取横向边结果
        for y in range(height):
            for x in range(width - 1):
                if h_edges[y, x].sol:
                    grid_x = x + min_x
                    grid_y = y + min_y
                    solution_objects.append({
                        "type": "Solve_mode", 
                        "x": grid_x, "y": grid_y, 
                        "data": {"dir": "right", "style": "line"}
                    })
        
        # 提取纵向边结果
        for y in range(height - 1):
            for x in range(width):
                if v_edges[y, x].sol:
                    grid_x = x + min_x
                    grid_y = y + min_y
                    solution_objects.append({
                        "type": "Solve_mode", 
                        "x": grid_x, "y": grid_y, 
                        "data": {"dir": "down", "style": "line"}
                    })
                    
        return solution_objects
    else:
        print("Solver (cspuz): 无解")
        return []

# --- 外部接口：推演 (逻辑确定性) ---
def deduct(problem_data):
    ctx = _build_model(problem_data)
    if not ctx: return []

    solver = ctx["solver"]
    h_edges = ctx["h_edges"]
    v_edges = ctx["v_edges"]
    min_x, min_y = ctx["min_x"], ctx["min_y"]
    width, height = ctx["width"], ctx["height"]
    valid_cells = ctx["valid_cells"]

    print("Deduct (cspuz): 开始逻辑推演...")

    # 计算所有可行解的公共部分 (Backbone)
    # 变量的 .sol 属性将为 True/False (确定) 或 None (不确定)
    has_solution = solver.solve()
    
    if not has_solution:
        print("Deduct (cspuz): 盘面无解")
        return []

    deduced_objects = []

    # 检查横向边确定性
    for y in range(height):
        for x in range(width - 1):
            val = h_edges[y, x].sol
            grid_x, grid_y = x + min_x, y + min_y
            
            if val is True:
                # 确定有线
                deduced_objects.append({
                    "type": "Solve_mode", "x": grid_x, "y": grid_y, 
                    "data": {"dir": "right", "style": "line"}
                })
            elif val is False:
                # 确定无线 (画叉，仅当两端都在有效区域内时)
                if (y, x) in valid_cells and (y, x+1) in valid_cells:
                    deduced_objects.append({
                        "type": "Solve_mode", "x": grid_x, "y": grid_y, 
                        "data": {"dir": "right", "style": "cross"}
                    })

    # 检查纵向边确定性
    for y in range(height - 1):
        for x in range(width):
            val = v_edges[y, x].sol
            grid_x, grid_y = x + min_x, y + min_y
            
            if val is True:
                deduced_objects.append({
                    "type": "Solve_mode", "x": grid_x, "y": grid_y, 
                    "data": {"dir": "down", "style": "line"}
                })
            elif val is False:
                if (y, x) in valid_cells and (y+1, x) in valid_cells:
                    deduced_objects.append({
                        "type": "Solve_mode", "x": grid_x, "y": grid_y, 
                        "data": {"dir": "down", "style": "cross"}
                    })

    print(f"Deduct (cspuz): 推演完成，发现 {len(deduced_objects)} 个确定项")
    return deduced_objects