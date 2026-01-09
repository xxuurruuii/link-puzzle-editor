# actions.py
import pygame
from map_objects import ITEM_REGISTRY

def place_object(editor, new_obj):
    """放置物品，处理层级冲突"""
    to_remove = []
    for obj in editor.objects:
        if obj.gx == new_obj.gx and obj.gy == new_obj.gy:
            if obj.layer_id == new_obj.layer_id:
                to_remove.append(obj)
    
    for obj in to_remove:
        editor.objects.remove(obj)
    editor.objects.append(new_obj)
    editor.objects.sort(key=lambda o: o.z_index)

def remove_object_at(editor, gx, gy, target_layer_id=None):
    """删除指定位置的物品"""
    candidates = [o for o in editor.objects if o.gx == gx and o.gy == gy]
    if not candidates: return

    if target_layer_id:
        for obj in candidates:
            if obj.layer_id == target_layer_id:
                editor.objects.remove(obj)
    else:
        candidates.sort(key=lambda o: o.z_index, reverse=True)
        if candidates:
            editor.objects.remove(candidates[0])

def handle_continuous_tool(editor, curr_gx, curr_gy, tool_cls):
    """处理连续拖拽工具的核心逻辑（如画线、画叉）"""
    prev_gx, prev_gy = editor.last_drag_grid
    if (curr_gx, curr_gy) == (prev_gx, prev_gy):
        return

    # 1. 计算目标边缘位置
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
        # 2. 检查该位置是否已有物品
        existing = None
        for obj in editor.objects:
            if obj.gx == target_obj.gx and obj.gy == target_obj.gy and obj.layer_id == target_obj.layer_id:
                existing = obj
                break
        
        # 3. 确定操作模式 (仅在拖拽开始时确定一次)
        is_right_btn = pygame.mouse.get_pressed()[2]
        if editor.edge_op_mode is None:
            if is_right_btn:
                if existing and existing.data.get('style') == 'cross':
                    editor.edge_op_mode = 'del_cross'
                else:
                    editor.edge_op_mode = 'draw_cross'
            else:
                if existing and existing.data.get('style') == 'line':
                    editor.edge_op_mode = 'del_line'
                else:
                    editor.edge_op_mode = 'draw_line'

        # 4. 执行增删改
        if editor.edge_op_mode == 'del_line' and existing and existing.data.get('style') == 'line':
            editor.objects.remove(existing)
        elif editor.edge_op_mode == 'del_cross' and existing and existing.data.get('style') == 'cross':
            editor.objects.remove(existing)
        elif editor.edge_op_mode == 'draw_line':
            target_obj.data['style'] = 'line'
            place_object(editor, target_obj)
        elif editor.edge_op_mode == 'draw_cross':
            target_obj.data['style'] = 'cross'
            place_object(editor, target_obj)

    editor.last_drag_grid = (curr_gx, curr_gy)