"""工具模块"""
import os
import json
import shutil
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox

# ===================== 配置 =====================
TEMP_FOLDER = "_image_temp"
DB_PATH = os.path.join(TEMP_FOLDER, "db.json")
RESULT_JS = os.path.join(TEMP_FOLDER, "duplicates.js")

def load_db():
    """加载数据库"""
    from core_scanner import load_db as load_db_scanner
    return load_db_scanner()

def save_db(db):
    """保存数据库"""
    from core_scanner import save_db as save_db_scanner
    save_db_scanner(db)

def get_device_info():
    """获取设备信息"""
    import torch
    device_info = {
        "cuda_available": torch.cuda.is_available(),
        "mps_available": torch.backends.mps.is_available(),
        "cpu_count": os.cpu_count()
    }
    
    if torch.cuda.is_available():
        device_info["device"] = "cuda"
        device_info["gpu_name"] = torch.cuda.get_device_name(0)
        device_info["gpu_memory"] = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
    elif torch.backends.mps.is_available():
        device_info["device"] = "mps"
        device_info["gpu_name"] = "Apple Silicon GPU"
    else:
        device_info["device"] = "cpu"
    
    return device_info

def format_file_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def get_file_info(file_path):
    """获取文件信息"""
    try:
        stat = os.stat(file_path)
        return {
            "size": stat.st_size,
            "size_formatted": format_file_size(stat.st_size),
            "modified": stat.st_mtime,
            "created": stat.st_ctime
        }
    except:
        return None

def create_thumbnail_image(file_path, max_size=(200, 200)):
    """创建缩略图图像"""
    try:
        img = Image.open(file_path)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)
    except:
        # 如果无法打开图片，返回一个默认图像
        return create_default_thumbnail(max_size)

def create_default_thumbnail(size=(200, 200)):
    """创建默认缩略图"""
    img = Image.new('RGB', size, color='gray')
    return ImageTk.PhotoImage(img)

def export_results_to_json(db, output_path=None):
    """导出结果到JSON文件"""
    if output_path is None:
        output_path = os.path.join(TEMP_FOLDER, "results.json")
    
    results = {
        "total_files": len(db.get("files", {})),
        "total_duplicates": len(db.get("duplicates", [])),
        "files": db.get("files", {}),
        "duplicates": db.get("duplicates", [])
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    return output_path

def export_results_to_csv(db, output_path=None):
    """导出结果到CSV文件"""
    if output_path is None:
        output_path = os.path.join(TEMP_FOLDER, "results.csv")
    
    import csv
    
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        
        # 写入文件列表
        writer.writerow(["文件列表"])
        writer.writerow(["序号", "文件路径", "缩略图ID"])
        for idx, (file_path, file_info) in enumerate(db.get("files", {}).items(), 1):
            writer.writerow([idx, file_path, file_info.get("id", "")])
        
        writer.writerow([])
        
        # 写入重复列表
        writer.writerow(["重复图片对"])
        writer.writerow(["组号", "图片A", "图片B"])
        for idx, dup_pair in enumerate(db.get("duplicates", []), 1):
            if len(dup_pair) >= 2:
                writer.writerow([idx, dup_pair[0], dup_pair[1]])
    
    return output_path

def delete_duplicate_files(db, duplicate_index):
    """删除重复文件"""
    duplicates = db.get("duplicates", [])
    if duplicate_index < 0 or duplicate_index >= len(duplicates):
        return False, "无效的索引"
    
    dup_pair = duplicates[duplicate_index]
    if len(dup_pair) < 2:
        return False, "无效的重复对"
    
    deleted_files = []
    errors = []
    
    # 删除第一个文件（保留第二个）
    try:
        if os.path.exists(dup_pair[0]):
            os.remove(dup_pair[0])
            deleted_files.append(dup_pair[0])
            
            # 从数据库中移除
            if dup_pair[0] in db["files"]:
                del db["files"][dup_pair[0]]
        else:
            errors.append(f"文件不存在: {dup_pair[0]}")
    except Exception as e:
        errors.append(f"删除文件失败 {dup_pair[0]}: {str(e)}")
    
    # 更新重复列表
    db["duplicates"].pop(duplicate_index)
    save_db(db)
    
    return True, {
        "deleted": deleted_files,
        "errors": errors
    }

def cleanup_temp_files():
    """清理临时文件"""
    try:
        if os.path.exists(TEMP_FOLDER):
            # 只删除缩略图文件，保留数据库和结果文件
            for file in os.listdir(TEMP_FOLDER):
                if file.endswith('.png') and file.startswith('img_'):
                    os.remove(os.path.join(TEMP_FOLDER, file))
        return True, "临时文件清理完成"
    except Exception as e:
        return False, f"清理临时文件失败: {str(e)}"

def reset_database():
    """重置数据库"""
    try:
        if os.path.exists(TEMP_FOLDER):
            shutil.rmtree(TEMP_FOLDER)
        os.makedirs(TEMP_FOLDER, exist_ok=True)
        
        db = {
            "state": "idle", "index": 0, "files": {}, "duplicates": [],
            "scan_processed": 0, "last_file_list": [], "last_file_count": 0
        }
        save_db(db)
        
        return True, "数据库已重置"
    except Exception as e:
        return False, f"重置数据库失败: {str(e)}"

class ProgressDialog:
    """进度对话框"""
    
    def __init__(self, parent, title="处理中", message="请稍候..."):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("300x150")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.dialog.winfo_height()) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        # 消息标签
        self.message_label = ttk.Label(self.dialog, text=message)
        self.message_label.pack(pady=20)
        
        # 进度条
        self.progress = ttk.Progressbar(self.dialog, mode='indeterminate')
        self.progress.pack(pady=10, padx=20, fill=tk.X)
        self.progress.start(10)
        
        # 取消按钮
        self.cancel_button = ttk.Button(self.dialog, text="取消", command=self.cancel)
        self.cancel_button.pack(pady=10)
        
        self.cancelled = False
    
    def cancel(self):
        """取消操作"""
        self.cancelled = True
        self.dialog.destroy()
    
    def update_message(self, message):
        """更新消息"""
        self.message_label.config(text=message)
        self.dialog.update()
    
    def close(self):
        """关闭对话框"""
        self.progress.stop()
        self.dialog.destroy()

def show_image_preview(parent, image_path, title="图片预览"):
    """显示图片预览"""
    preview = tk.Toplevel(parent)
    preview.title(title)
    preview.transient(parent)
    
    try:
        img = Image.open(image_path)
        img.thumbnail((800, 600), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        
        label = ttk.Label(preview, image=photo)
        label.image = photo  # 保持引用
        label.pack(padx=10, pady=10)
        
        # 文件信息
        file_info = get_file_info(image_path)
        if file_info:
            info_text = f"文件: {os.path.basename(image_path)}\n"
            info_text += f"大小: {file_info['size_formatted']}\n"
            info_text += f"路径: {image_path}"
            
            info_label = ttk.Label(preview, text=info_text, justify=tk.LEFT)
            info_label.pack(padx=10, pady=(0, 10))
        
        # 居中显示
        preview.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - preview.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - preview.winfo_height()) // 2
        preview.geometry(f"+{x}+{y}")
        
    except Exception as e:
        messagebox.showerror("错误", f"无法预览图片: {str(e)}", parent=preview)
        preview.destroy()