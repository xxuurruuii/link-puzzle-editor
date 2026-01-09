# io_handler.py
import json
import tkinter as tk
from tkinter import filedialog
from map_objects import ITEM_REGISTRY

def save_map_to_json(objects):
    """保存当前对象列表为JSON"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.asksaveasfilename(
        defaultextension=".json", filetypes=[("JSON", "*.json")], title="保存"
    )
    root.destroy()
    
    if not file_path:
        return None, "取消保存"

    try:
        data = [obj.to_dict() for obj in objects]
        with open(file_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        return file_path, f"保存成功: {file_path.split('/')[-1]}"
    except Exception as e:
        print(e)
        return None, "保存失败"

def load_map_from_json():
    """从JSON文件读取并重建对象列表"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        filetypes=[("JSON", "*.json")], title="读取"
    )
    root.destroy()
    
    if not file_path:
        return None, "取消读取"

    try:
        with open(file_path, "r", encoding='utf-8') as f:
            data = json.load(f)
        
        new_objects = []
        name_map = {cls.__name__: cls for cls in ITEM_REGISTRY}
        
        for item_data in data:
            cls_name = item_data['type']
            if cls_name in name_map:
                new_objects.append(name_map[cls_name].from_dict(item_data))
        
        return new_objects, f"读取成功: {file_path.split('/')[-1]}"
    except Exception as e:
        print(e)
        return None, "读取失败"