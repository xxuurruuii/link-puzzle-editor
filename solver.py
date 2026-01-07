import sys
from collections import defaultdict
import grilops
import grilops.paths
from z3 import sat, unsat, Or, Not

# --- 辅助函数：构建模型 ---
def _build_model(problem_data):
    """
    根据传入的数据构建 Grilops 模型和 Solver 实例，但不进行求解。
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

    # 2. 数据分类
    floor_cells = set()
    endpoints = {}
    number_to_points = defaultdict(list)

    for obj in objects:
        pos = (obj['x'], obj['y'])
        t = obj['type']
        
        if t == 'FloorCell':
            floor_cells.add(pos)
        elif t == 'EndPoint':
            floor_cells.add(pos)
            num = obj.get('data', {}).get('num', 1)
            endpoints[pos] = num
            number_to_points[num].append(pos)

    # 3. 初始化 Grilops
    lattice = grilops.get_rectangle_lattice(height, width)
    sym = grilops.paths.PathSymbolSet(lattice)
    sym.append("EMPTY", ".")
    
    sg = grilops.SymbolGrid(lattice, sym)
    pc = grilops.paths.PathConstrainer(sg, allow_loops=False)

    # 4. 添加基础约束
    for p in lattice.points:
        grid_x = p.x + min_x
        grid_y = p.y + min_y
        pos = (grid_x, grid_y)
        cell = sg.grid[p]

        # 端点约束
        if pos in endpoints:
            sg.solver.add(sym.is_terminal(cell))
        else:
            sg.solver.add(Not(sym.is_terminal(cell)))
            
        # 地形约束
        if pos not in floor_cells:
            sg.solver.add(sg.cell_is(p, sym.EMPTY))

    # Numberlink 连通性约束
    for num, points_list in number_to_points.items():
        if len(points_list) == 2:
            p1 = points_list[0]
            p2 = points_list[1]
            # 转换为 grilops 坐标 (row, col) = (y, x)
            pt1 = grilops.Point(p1[1] - min_y, p1[0] - min_x)
            pt2 = grilops.Point(p2[1] - min_y, p2[0] - min_x)
            
            pid = lattice.point_to_index(pt1)
            sg.solver.add(pc.path_instance_grid[pt1] == pid)
            sg.solver.add(pc.path_instance_grid[pt2] == pid)

    # 打包上下文返回
    return {
        "sg": sg,
        "sym": sym,
        "lattice": lattice,
        "min_x": min_x,
        "min_y": min_y,
        "floor_cells": floor_cells # 用于 deduct 判断是否画叉
    }

# --- 求解函数 ---
def solve(problem_data):
    ctx = _build_model(problem_data)
    if not ctx: return []
    
    sg = ctx["sg"]
    sym = ctx["sym"]
    lattice = ctx["lattice"]
    min_x, min_y = ctx["min_x"], ctx["min_y"]

    # --- 修改 A: 显式定义包含方向的符号列表 ---
    # 向右连接：包含 EW, NE, SE 以及 端点向右(E)
    symbols_with_E = [sym.EW, sym.NE, sym.SE, sym.E]
    
    # 向下连接：包含 NS, SE, SW 以及 端点向下(S)
    symbols_with_S = [sym.NS, sym.SE, sym.SW, sym.S]
    # ---------------------------------------

    solution_objects = []
    print("Solver: 开始求解...")
    
    if sg.solve():
        print("Solver: 求解成功")
        solved_grid = sg.solved_grid()
        for p in lattice.points:
            # 获取该格子的符号索引 (整数)
            symbol_idx = solved_grid[p]
            
            # 如果是 EMPTY 则跳过
            if symbol_idx == sym.EMPTY: 
                continue
            
            grid_x, grid_y = p.x + min_x, p.y + min_y
            
            # --- 修改 B: 使用列表成员检查代替字符串检查 ---
            if symbol_idx in symbols_with_E:
                solution_objects.append({"type": "Solve_mode", "x": grid_x, "y": grid_y, "data": {"dir": "right", "style": "line"}})
            
            if symbol_idx in symbols_with_S:
                solution_objects.append({"type": "Solve_mode", "x": grid_x, "y": grid_y, "data": {"dir": "down", "style": "line"}})
            # -----------------------------------------
    else:
        print("Solver: 无解")

    return solution_objects

# --- 推理函数 ---
def deduct(problem_data):
    ctx = _build_model(problem_data)
    if not ctx: return []

    sg = ctx["sg"]
    sym = ctx["sym"]
    lattice = ctx["lattice"]
    min_x, min_y = ctx["min_x"], ctx["min_y"]
    floor_cells = ctx["floor_cells"]

    if not sg.solve():
        print("Deduct: 盘面本身无解")
        return []

    print("Deduct: 盘面有解，开始进行逻辑推演...")
    deduced_objects = []

    # --- 修改 C: 显式定义方向列表 (同 solve) ---
    # 向右连接：包含 EW, NE, SE 以及 端点向右(E)
    symbols_with_E = [sym.EW, sym.NE, sym.SE, sym.E]
    
    # 向下连接：包含 NS, SE, SW 以及 端点向下(S)
    symbols_with_S = [sym.NS, sym.SE, sym.SW, sym.S]
    # ---------------------------------------

    # 定义检查函数 (逻辑保持不变，但传入的 direction_symbols 现在是干净的整数列表)
    def check_edge(p, direction_symbols, output_dir):
        cell_var = sg.grid[p]
        
        # 构造约束：该格子取值必须在给定的列表中
        # Z3 表达式: Or(cell == sym.EW, cell == sym.NE, ...)
        has_line_constraint = Or([cell_var == s_idx for s_idx in direction_symbols])
        
        # 1. 测试“必须有线”
        sg.solver.push()
        sg.solver.add(has_line_constraint)
        can_be_line = (sg.solver.check() == sat)
        sg.solver.pop()

        # 2. 测试“必须无线”
        sg.solver.push()
        sg.solver.add(Not(has_line_constraint))
        can_be_empty = (sg.solver.check() == sat)
        sg.solver.pop()

        grid_x, grid_y = p.x + min_x, p.y + min_y

        if can_be_line and not can_be_empty:
            return {"type": "Solve_mode", "x": grid_x, "y": grid_y, "data": {"dir": output_dir, "style": "line"}}
        
        elif not can_be_line and can_be_empty:
            # 仅当两边都是 FloorCell 时才画叉
            neighbor_x, neighbor_y = grid_x, grid_y
            if output_dir == 'right': neighbor_x += 1
            elif output_dir == 'down': neighbor_y += 1
            
            if (grid_x, grid_y) in floor_cells and (neighbor_x, neighbor_y) in floor_cells:
                return {"type": "Solve_mode", "x": grid_x, "y": grid_y, "data": {"dir": output_dir, "style": "cross"}}
        
        return None

    total_steps = len(lattice.points)
    for i, p in enumerate(lattice.points):
        if i % 10 == 0: print(f"Deducting: {i}/{total_steps}", end='\r')

        # 检查向右
        res_right = check_edge(p, symbols_with_E, 'right')
        if res_right: deduced_objects.append(res_right)

        # 检查向下
        res_down = check_edge(p, symbols_with_S, 'down')
        if res_down: deduced_objects.append(res_down)

    print(f"\nDeduct: 推演完成，发现 {len(deduced_objects)} 个确定项")
    return deduced_objects