import sys
from collections import defaultdict
import grilops
import grilops.paths
from z3 import sat, unsat, Or, Not, PbEq, If, Implies

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
    simpleloops = []
    slitherlinks = []

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
        elif t == 'Simpleloop':
            simpleloops.append(pos)
        elif t == 'Slitherlink':
            slitherlinks.append(obj)

    # 3. 初始化 Grilops
    lattice = grilops.get_rectangle_lattice(height, width)
    sym = grilops.paths.PathSymbolSet(lattice)
    sym.append("EMPTY", ".")
    
    sg = grilops.SymbolGrid(lattice, sym)
    pc = grilops.paths.PathConstrainer(sg, allow_loops=False)

    # 定义各方向对应的符号集合
    s_E = [sym.EW, sym.NE, sym.SE, sym.E]
    s_W = [sym.EW, sym.NW, sym.SW, sym.W]
    s_S = [sym.NS, sym.SE, sym.SW, sym.S]
    s_N = [sym.NS, sym.NE, sym.NW, sym.N]

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

    # 已有线条约束

    # 辅助函数: 安全获取格子变量
    def get_cell(gx, gy):
        if min_x <= gx <= max_x and min_y <= gy <= max_y:
            return sg.grid[grilops.Point(gy - min_y, gx - min_x)]
        return None

    # 第二次遍历对象，处理 Solve_mode
    for obj in objects:
        if obj['type'] == 'Solve_mode':
            d = obj.get('data', {})
            direction = d.get('dir', 'right')
            style = d.get('style', 'line')
            gx, gy = obj['x'], obj['y']

            # 获取当前格和目标格（连线另一端）的变量
            c_curr = get_cell(gx, gy)
            if direction == 'right':
                c_next = get_cell(gx + 1, gy)
                target_syms_curr, target_syms_next = s_E, s_W
            elif direction == 'down':
                c_next = get_cell(gx, gy + 1)
                target_syms_curr, target_syms_next = s_S, s_N
            else:
                continue

            # 构造约束表达式
            # 如果格子在范围内，创建 "该格子取值必须属于特定方向集合" 的逻辑
            constraint_curr = Or([c_curr == s for s in target_syms_curr]) if c_curr is not None else None
            constraint_next = Or([c_next == s for s in target_syms_next]) if c_next is not None else None

            if style == 'line':
                # 如果是线：强制该格必须连通
                if constraint_curr is not None: sg.solver.add(constraint_curr)
                if constraint_next is not None: sg.solver.add(constraint_next)
            elif style == 'cross':
                # 如果是叉：强制该格不能连通
                if constraint_curr is not None: sg.solver.add(Not(constraint_curr))
                if constraint_next is not None: sg.solver.add(Not(constraint_next))

    # Simpleloop 约束：该格子的符号不能是 EMPTY (必须有线经过)
    for pos in simpleloops:
        # 转换为 grilops 坐标
        pt = grilops.Point(pos[1] - min_y, pos[0] - min_x)
        sg.solver.add(sg.grid[pt] != sym.EMPTY)

    # Slitherlink 约束：周围满足连接条件的数量必须等于数字
    for obj in slitherlinks:
        gx, gy = obj['x'], obj['y']
        target_num = obj['data'].get('num', 0)
        
        # 定义：顶点 (gx, gy) 实际上是 格子(gx, gy) 的左上角顶点
        # 它涉及到四个周围格子的连接情况：
        # TL (Top-Left) : (gx-1, gy-1)
        # TR (Top-Right): (gx,   gy-1)
        # BL (Bottom-Left):(gx-1, gy)
        
        terms = []

        # 1. 顶点上方边 (连接 TL 和 TR): 检查 TL 是否向东连接
        c_tl = get_cell(gx - 1, gy - 1)
        if c_tl is not None:
            terms.append((Or([c_tl == s for s in s_E]), 1))

        # 2. 顶点左方边 (连接 TL 和 BL): 检查 TL 是否向南连接
        if c_tl is not None:
            terms.append((Or([c_tl == s for s in s_S]), 1))

        # 3. 顶点下方边 (连接 BL 和 BR): 检查 BL 是否向东连接
        c_bl = get_cell(gx - 1, gy)
        if c_bl is not None:
            terms.append((Or([c_bl == s for s in s_E]), 1))

        # 4. 顶点右方边 (连接 TR 和 BR): 检查 TR 是否向南连接
        c_tr = get_cell(gx, gy - 1)
        if c_tr is not None:
            terms.append((Or([c_tr == s for s in s_S]), 1))

        sg.solver.add(PbEq(terms, target_num))

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

    # 1. 获取第一个解 (基准解)
    if not sg.solve():
        print("Deduct: 盘面无解")
        return []

    print("Deduct: 找到基准解，开始迭代求交 (Backbone Computing)...")
    
    # 辅助定义：方向集合
    s_E = [sym.EW, sym.NE, sym.SE, sym.E]
    s_S = [sym.NS, sym.SE, sym.SW, sym.S]

    # 2. 初始化“候选确定项”
    # 结构: candidates[(x, y, dir)] = True(必须有线) / False(必须无线)
    # 我们只关心 right 和 down 两个方向的边
    candidates = {}
    
    first_grid = sg.solved_grid()

    for p in lattice.points:
        grid_x, grid_y = p.x + min_x, p.y + min_y
        cell_val = first_grid[p]

        # 检查向右的边 (Right)
        has_right = (cell_val in s_E)
        candidates[(p, 'right')] = has_right

        # 检查向下的边 (Down)
        has_down = (cell_val in s_S)
        candidates[(p, 'down')] = has_down

    # 3. 迭代循环：寻找反例
    iteration = 1
    while True:
        # 构建“反例约束”：
        # 我们要求求解器寻找一个新的解，这个解必须 至少有一个 还在候选列表中的边 发生了翻转。
        # Blocking Clause: Or( edge_state != expected_state for all edge in candidates )
        
        blocking_clauses = []
        current_candidate_keys = list(candidates.keys())
        
        if not current_candidate_keys:
            break # 没有任何确定项了（全都不确定），直接退出

        for key in current_candidate_keys:
            p, direction = key
            expected_val = candidates[key]
            
            cell_var = sg.grid[p]
            target_syms = s_E if direction == 'right' else s_S
            
            # Z3 逻辑：当前格子的变量是否包含该方向的线
            # Or([cell_var == s for s in target_syms]) 表示“有线”
            is_line_expr = Or([cell_var == s_idx for s_idx in target_syms])
            
            if expected_val:
                # 期望是 True (有线)，我们要找它是 False (无线) 的情况
                # 即加入 Not(is_line_expr) 到“或”子句中
                blocking_clauses.append(Not(is_line_expr))
            else:
                # 期望是 False (无线)，我们要找它是 True (有线) 的情况
                blocking_clauses.append(is_line_expr)
        
        # 添加约束：新解必须至少满足一个“翻转”
        sg.solver.add(Or(blocking_clauses))
        
        print(f"Deduct: 迭代第 {iteration} 次，剩余候选数: {len(candidates)}")
        
        # 求解
        if sg.solve():
            # 找到了一个反例解 (Counter-example)
            new_grid = sg.solved_grid()
            
            # 剔除那些发生变化的边
            keys_to_remove = []
            for key, old_val in candidates.items():
                p, direction = key
                cell_val = new_grid[p]
                target_syms = s_E if direction == 'right' else s_S
                new_val = (cell_val in target_syms)
                
                if new_val != old_val:
                    keys_to_remove.append(key)
            
            for k in keys_to_remove:
                del candidates[k]
                
            iteration += 1
        else:
            # 无法找到反例，说明剩下的 candidates 全是固定不变的
            print("Deduct: 收敛，未找到更多反例。")
            break

    # 4. 生成结果对象
    deduced_objects = []
    for (p, direction), is_line in candidates.items():
        grid_x, grid_y = p.x + min_x, p.y + min_y
        
        if is_line:
            # 确定有线
            deduced_objects.append({
                "type": "Solve_mode", 
                "x": grid_x, 
                "y": grid_y, 
                "data": {"dir": direction, "style": "line"}
            })
        else:
            # 确定无线（画叉）
            # 只有当两侧都是 FloorCell 时才画叉 (保持原有逻辑)
            neighbor_x, neighbor_y = grid_x, grid_y
            if direction == 'right': neighbor_x += 1
            elif direction == 'down': neighbor_y += 1
            
            if (grid_x, grid_y) in floor_cells and (neighbor_x, neighbor_y) in floor_cells:
                deduced_objects.append({
                    "type": "Solve_mode", 
                    "x": grid_x, 
                    "y": grid_y, 
                    "data": {"dir": direction, "style": "cross"}
                })

    print(f"Deduct: 推演完成，发现 {len(deduced_objects)} 个确定项")
    return deduced_objects