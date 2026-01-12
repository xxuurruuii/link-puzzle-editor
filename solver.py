# solver.py
import sys
from collections import defaultdict
from cspuz.solver import Solver
from cspuz.graph import Graph, active_edges_acyclic
from cspuz.constraints import count_true

# --- 辅助函数：构建模型 ---
def _build_model(problem_data):
    """
    根据传入的数据构建 cspuz 模型。
    返回上下文信息供 solve 和 deduct 使用。
    """
    objects = problem_data
    if not objects:
        return None

    # 1. 提取坐标范围
    xs = [obj['x'] for obj in objects]
    ys = [obj['y'] for obj in objects]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    # 2. 数据映射
    valid_cells = set()
    endpoints = {}
    simpleloops = set()
    slitherlinks = []
    walls = set() 
    
    max_num = 0

    for obj in objects:
        # 将全局坐标转换为 0 索引的局部坐标
        lx = obj['x'] - min_x
        ly = obj['y'] - min_y
        pos = (ly, lx) # (row, col)
        t = obj['type']
        
        if t == 'FloorCell':
            valid_cells.add(pos)
        elif t == 'Simpleloop':
            valid_cells.add(pos)
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
            # Slitherlink 位于格点，记录原始对象以便后续获取 num
            slitherlinks.append(obj)

    # 3. 初始化 Solver
    solver = Solver()

    # 4. 定义变量
    # path_id: 每个格子的线路编号 (0表示空)
    # 注意: 如果 max_num 为 0 (无端点)，这也不会报错，只是范围为 0..0
    path_id = solver.int_array((height, width), 0, max_num)
    
    # h_edges: 横向边 (y, x) -- (y, x+1)
    h_edges = solver.bool_array((height, width - 1))
    # v_edges: 纵向边 (y, x) -- (y+1, x)
    v_edges = solver.bool_array((height - 1, width))

    # 已有线条和叉的标记
    for obj in objects:
        if obj['type'] == 'Solve_mode':
            # 转换局部坐标
            lx = obj['x'] - min_x
            ly = obj['y'] - min_y
            
            d = obj.get('data', {})
            direction = d.get('dir', 'right')
            style = d.get('style', 'line')
            
            if direction == 'right':
                # 横向边: h_edges[ly, lx]
                # 边界检查: 确保该边在定义的网格范围内
                if 0 <= ly < height and 0 <= lx < width - 1:
                    edge = h_edges[ly, lx]
                    if style == 'line':
                        solver.ensure(edge)        # 必须有线 (True)
                    elif style == 'cross':
                        solver.ensure(~edge)       # 必须无线 (False, 使用 ~ 取反)
                        
            elif direction == 'down':
                # 纵向边: v_edges[ly, lx]
                if 0 <= ly < height - 1 and 0 <= lx < width:
                    edge = v_edges[ly, lx]
                    if style == 'line':
                        solver.ensure(edge)
                    elif style == 'cross':
                        solver.ensure(~edge)

    # 5. 构建图与添加约束
    graph = Graph(height * width)
    all_active_edges = []

    # 添加横向边
    for y in range(height):
        for x in range(width - 1):
            u = y * width + x
            v = y * width + (x + 1)
            graph.add_edge(u, v)
            all_active_edges.append(h_edges[y, x])
            # 流约束：如果边连通，则两侧 ID 必须相同
            solver.ensure(h_edges[y, x].then(path_id[y, x] == path_id[y, x + 1]))

    # 添加纵向边
    for y in range(height - 1):
        for x in range(width):
            u = y * width + x
            v = (y + 1) * width + x
            graph.add_edge(u, v)
            all_active_edges.append(v_edges[y, x])
            # 流约束
            solver.ensure(v_edges[y, x].then(path_id[y, x] == path_id[y + 1, x]))

    # A. 无环约束
    active_edges_acyclic(solver, all_active_edges, graph)

    # B. 单元格约束
    for y in range(height):
        for x in range(width):
            pos = (y, x)
            
            # 获取当前格子的周围边
            neighbors = []
            if x > 0: neighbors.append(h_edges[y, x - 1])         # 左
            if x < width - 1: neighbors.append(h_edges[y, x])     # 右
            if y > 0: neighbors.append(v_edges[y - 1, x])         # 上
            if y < height - 1: neighbors.append(v_edges[y, x])    # 下
            
            degree = count_true(neighbors)
            
            # 标记：当前格子是否受到特殊线索的约束
            is_constrained = False
            
            if pos in endpoints:
                # 端点：度数必须为 1，且 ID 固定
                solver.ensure(degree == 1)
                solver.ensure(path_id[y, x] == endpoints[pos])
                is_constrained = True
            if pos in walls:
                # 墙壁约束: 必须没有任何线条经过
                solver.ensure(degree == 0)
                solver.ensure(path_id[y, x] == 0)
                is_constrained = True
            if pos in simpleloops:
                # Simpleloop: 必须有线经过 (度数为2，且ID非0)
                solver.ensure(degree == 2)
                solver.ensure(path_id[y, x] != 0)
                is_constrained = True
            if not is_constrained:
                if pos in valid_cells:
                    # 普通地板：可以是通路(2)也可以是空(0)
                    solver.ensure((degree == 0) | (degree == 2))
                    solver.ensure((degree == 0) == (path_id[y, x] == 0))
                else:
                    # 空白区域/非法区域：必须为空
                    solver.ensure(degree == 0)
                    solver.ensure(path_id[y, x] == 0)

    # Slitherlink约束
    for obj in slitherlinks:
        # 计算局部坐标 (Slitherlink 位于格点 vertex)
        lx = obj['x'] - min_x
        ly = obj['y'] - min_y
        target_num = obj.get('data', {}).get('num', 0)
        
        # 收集该顶点周围的 4 条边
        # 顶点 (ly, lx) 是格子 (ly, lx) 的左上角
        # 涉及的格子索引: TL(ly-1, lx-1), TR(ly-1, lx), BL(ly, lx-1), BR(ly, lx)
        # 边定义:
        # h_edges[y, x] 连接 (y, x) 和 (y, x+1)
        # v_edges[y, x] 连接 (y, x) 和 (y+1, x)
        
        neighbors = []

        # 1. 上方边 (连接 TL 和 TR): h_edges[ly-1, lx-1]
        if 0 <= ly - 1 < height and 0 <= lx - 1 < width - 1:
            neighbors.append(h_edges[ly - 1, lx - 1])

        # 2. 下方边 (连接 BL 和 BR): h_edges[ly, lx-1]
        if 0 <= ly < height and 0 <= lx - 1 < width - 1:
            neighbors.append(h_edges[ly, lx - 1])

        # 3. 左方边 (连接 TL 和 BL): v_edges[ly-1, lx-1]
        if 0 <= ly - 1 < height - 1 and 0 <= lx - 1 < width:
            neighbors.append(v_edges[ly - 1, lx - 1])

        # 4. 右方边 (连接 TR 和 BR): v_edges[ly-1, lx]
        if 0 <= ly - 1 < height - 1 and 0 <= lx < width:
            neighbors.append(v_edges[ly - 1, lx])

        # 约束: 周围存在的边数量等于数字
        solver.ensure(count_true(neighbors) == target_num)

    # 6. 设置 Answer Key
    # 标记 path_id 为答案，使得 solver.solve() 知道针对哪些变量计算骨架
    solver.add_answer_key(path_id)
    # 标记边为答案，确保在 deduct 模式下能读取边的 .sol 状态
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

# --- 求解函数 (获取单一解) ---
def solve(problem_data):
    ctx = _build_model(problem_data)
    if not ctx: return []

    solver = ctx["solver"]
    h_edges = ctx["h_edges"]
    v_edges = ctx["v_edges"]
    min_x, min_y = ctx["min_x"], ctx["min_y"]
    width, height = ctx["width"], ctx["height"]

    print("Solver (cspuz): 开始求解...")
    
    # find_answer() 不需要 Answer Key 也能运行，但为了统一性我们加了
    if solver.find_answer():
        print("Solver (cspuz): 求解成功")
        solution_objects = []
        
        # 提取横向边
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
        
        # 提取纵向边
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

# --- 推理函数 (逻辑推演) ---
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

    # 使用 solve() 计算所有解的公共部分 (Backbone)
    # 必须有 Answer Key 才能正常工作
    has_solution = solver.solve()
    
    if not has_solution:
        print("Deduct (cspuz): 盘面无解")
        return []

    deduced_objects = []

    # 检查横向边
    for y in range(height):
        for x in range(width - 1):
            # .sol 为 True: 必定有线
            # .sol 为 False: 必定无线
            # .sol 为 None: 不确定
            val = h_edges[y, x].sol
            grid_x, grid_y = x + min_x, y + min_y
            
            if val is True:
                deduced_objects.append({
                    "type": "Solve_mode", "x": grid_x, "y": grid_y, 
                    "data": {"dir": "right", "style": "line"}
                })
            elif val is False:
                # 仅当两端都是有效格子时才标记叉
                if (y, x) in valid_cells and (y, x+1) in valid_cells:
                    deduced_objects.append({
                        "type": "Solve_mode", "x": grid_x, "y": grid_y, 
                        "data": {"dir": "right", "style": "cross"}
                    })

    # 检查纵向边
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