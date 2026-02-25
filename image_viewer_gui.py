import os
import sys
import json
import time
import psutil
import shutil
import threading
import winsound
import traceback
import subprocess
import tkinter as tk
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageTk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from core_scanner import Scanner, load_db, save_db, scan_images
from core_comparator import Comparator
from core_utils import get_device_info, format_file_size, get_file_info,create_thumbnail_image, create_default_thumbnail,export_results_to_json, export_results_to_csv,delete_duplicate_files, cleanup_temp_files, reset_database,ProgressDialog, show_image_preview as show_preview

# ===================== 调试 =====================
RUN_MODE = 0  # 0 = 自动，1 = GPU，2 = 多进程
RUN_Ver = 1 # 0 = A版，1 = B版
# ===================== 配置 =====================

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent / relative_path

MODEL_PATH = get_resource_path("tiny_similarity.pth")
TEMP_FOLDER = "_image_temp"
DB_PATH = os.path.join(TEMP_FOLDER, "db.json")
RESULT_JS = os.path.join(TEMP_FOLDER, "duplicates.js")
IMG_MAX_SIZE = 400
IMG_INPUT_SIZE = 128
DEFAULT_ALLOW_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif", ".gif"}

if RUN_Ver == 1:
    DEFAULT_CONFIG = {
        "similarity_threshold": 0.9963,
        "break_on_error": True,
        "print_error_log": True,
        "show_delete_confirm": True,
        "allowed_extensions": list(DEFAULT_ALLOW_EXTS)  
    }
else:
    DEFAULT_CONFIG = {
        "similarity_threshold": 0.9974,
        "break_on_error": True,
        "print_error_log": True,
        "show_delete_confirm": True,
        "allowed_extensions": list(DEFAULT_ALLOW_EXTS)  
    }


CONFIG_PATH = os.path.join(TEMP_FOLDER, "config.json")

def play_system_sound(sound_name, async_play=True):
    
    flags = winsound.SND_ALIAS
    if async_play:
        flags |= winsound.SND_ASYNC

    media_path = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'Media')
    sound_file = os.path.join(media_path, f"{sound_name}.wav")
    
    if os.path.exists(sound_file):
        try:
            winsound.PlaySound(sound_file, winsound.SND_FILENAME | (winsound.SND_ASYNC if async_play else 0))
            return True
        except RuntimeError:
            pass
    return False


def load_config():
    """加载配置文件"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            for key in DEFAULT_CONFIG.keys():
                if key not in config:
                    config[key] = DEFAULT_CONFIG[key]
            
            return config
        else:
            os.makedirs(TEMP_FOLDER, exist_ok=True)
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
            
            return DEFAULT_CONFIG.copy()
    except Exception as e:
        print(f"配置文件加载失败，使用默认值: {str(e)}")
        try:
            os.makedirs(TEMP_FOLDER, exist_ok=True)
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except:
            pass
        
        return DEFAULT_CONFIG.copy()

config = load_config()
SIMILARITY_THRESH = config.get("similarity_threshold", 0.9963)

device_info = get_device_info()
DEVICE = device_info["device"]
USE_GPU_INFERENCE = False

if RUN_MODE == 1:
    USE_GPU_INFERENCE = True
elif RUN_MODE == 2:
    USE_GPU_INFERENCE = False
else:
    USE_GPU_INFERENCE = (DEVICE != "cpu")

# ===================== GUI 主程序 =====================
class ImageDuplicateCheckerGUI:
    def __init__(self, root):
        self.root = root

        if RUN_Ver == 1:
            self.root.title("图片查重工具 - B版")
        else:
            self.root.title("图片查重工具 - A版")

        self.root.geometry("1200x800")
        
        self.setup_window_icon()
        
        self.setup_styles()
        
        self.db = load_db()
        self.scanning = False
        self.comparing = False
        
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.create_page1()  # 第一页：处理控制
        self.create_page2()  # 第二页：扫描结果
        self.create_page3()  # 第三页：重复图片
        self.create_page4()  # 第四页：设置
        
        self.create_status_bar()

    def setup_window_icon(self):
        """设置窗口图标"""
        try:
            icon_path = get_resource_path("icon.png")
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon)
                self.root.icon_image = icon  #
        except Exception as e:
            print(f"设置窗口图标失败: {str(e)}")
    
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        self.root.configure(bg='#DCDAD5')
        
        style.configure('Title.TLabel', font=('微软雅黑', 16, 'bold'))
        style.configure('Subtitle.TLabel', font=('微软雅黑', 12))
        style.configure('Success.TLabel', foreground='green')
        style.configure('Warning.TLabel', foreground='orange')
        style.configure('Error.TLabel', foreground='red')

        style.configure('TFrame', background='#DCDAD5')
        style.configure('TLabelFrame', background='#DCDAD5')
        style.configure('TLabelframe.Label', background='#DCDAD5')
        
    def create_page1(self):
        """第一页-处理控制页面"""
        self.page1 = ttk.Frame(self.notebook)
        self.notebook.add(self.page1, text="🔍   图片扫描")

        title_label = ttk.Label(self.page1, text="图片查重扫描", style='Title.TLabel')
        title_label.pack(pady=20)

        info_frame = ttk.LabelFrame(self.page1, text="系统资源", padding=15)
        info_frame.pack(fill=tk.X, padx=20, pady=10)

        self.system_resources_label = ttk.Label(info_frame, text="正在获取系统资源...", font=('微软雅黑', 10))
        self.system_resources_label.pack(anchor=tk.W)

        self.update_system_resources()

        control_frame = ttk.LabelFrame(self.page1, text="处理控制", padding=15)
        control_frame.pack(fill=tk.X, padx=20, pady=10)

        self.scan_btn = ttk.Button(control_frame, text="🔍   开始扫描图片", 
                                   command=self.start_scan, width=20)
        self.scan_btn.grid(row=0, column=0, padx=5, pady=5)

        self.compare_btn = ttk.Button(control_frame, text="⚡   开始比对重复", 
                                      command=self.start_compare, width=20)
        self.compare_btn.grid(row=0, column=1, padx=5, pady=5)

        self.stop_btn = ttk.Button(control_frame, text="⏹️   停止处理", 
                                   command=self.stop_processing, width=20, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=2, padx=5, pady=5)

        self.clear_log_btn = ttk.Button(control_frame, text="🗑️ 清空日志", 
                                       command=self.clear_log, width=20)
        self.clear_log_btn.grid(row=0, column=3, padx=5, pady=5)

        progress_frame = ttk.LabelFrame(self.page1, text="处理进度", padding=15)
        progress_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        scan_frame = ttk.Frame(progress_frame)
        scan_frame.pack(fill=tk.X, pady=5)
        
        self.scan_label = ttk.Label(scan_frame, text="扫描进度: 等待开始", anchor=tk.W)
        self.scan_label.pack(fill=tk.X, pady=(0, 5))
        
        self.scan_progress = ttk.Progressbar(scan_frame, mode='determinate')
        self.scan_progress.pack(fill=tk.X, pady=(0, 10))

        compare_frame = ttk.Frame(progress_frame)
        compare_frame.pack(fill=tk.X, pady=5)
        
        self.compare_label = ttk.Label(compare_frame, text="比对进度: 等待开始", anchor=tk.W)
        self.compare_label.pack(fill=tk.X, pady=(0, 5))
        
        self.compare_progress = ttk.Progressbar(compare_frame, mode='determinate')
        self.compare_progress.pack(fill=tk.X, pady=(0, 10))

        log_frame = ttk.LabelFrame(self.page1, text="处理日志", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=80)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
    def create_page2(self):
        """第二页-回收站页面"""
        self.page2 = ttk.Frame(self.notebook)
        self.notebook.add(self.page2, text="🗑️回收站")
        
        title_label = ttk.Label(self.page2, text="管理回收站", style='Title.TLabel')
        title_label.pack(pady=20)

        stats_frame = ttk.LabelFrame(self.page2, text="回收站统计", padding=15)
        stats_frame.pack(fill=tk.X, padx=20, pady=10)
        
        self.recycle_count_label = ttk.Label(stats_frame, text="回收站文件数: 0", font=('微软雅黑', 12, 'bold'))
        self.recycle_count_label.pack(anchor=tk.W)
        
        self.recycle_size_label = ttk.Label(stats_frame, text="总大小: 0 MB")
        self.recycle_size_label.pack(anchor=tk.W)

        btn_frame = ttk.Frame(self.page2)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        ttk.Button(btn_frame, text="🔄   刷新列表", 
                  command=self.refresh_recycle_list, width=14).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📁   打开回收站", 
                  command=self.open_recycle_folder, width=14).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️全部删除", 
                  command=self.delete_all_recycle_files, width=14).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="↩️   全部还原", 
                  command=self.restore_all_recycle_files, width=14).pack(side=tk.LEFT, padx=2)

        list_frame = ttk.LabelFrame(self.page2, text="回收站文件列表", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        columns = ('序号', '原路径', '删除时间', '大小')
        self.recycle_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.recycle_tree.heading(col, text=col)
            self.recycle_tree.column(col, width=100)
        
        self.recycle_tree.column('序号', width=60)
        self.recycle_tree.column('原路径', width=400)
        self.recycle_tree.column('删除时间', width=150)
        self.recycle_tree.column('大小', width=80)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.recycle_tree.yview)
        self.recycle_tree.configure(yscrollcommand=scrollbar.set)
        
        self.recycle_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.recycle_menu = tk.Menu(self.root, tearoff=0)
        self.recycle_menu.add_command(label="👁️ 查看大图", command=self.view_recycle_image)
        self.recycle_menu.add_command(label="📁     打开文件位置", command=self.open_recycle_file_location)
        self.recycle_menu.add_command(label="↩️     还原文件", command=self.restore_recycle_file)
        self.recycle_menu.add_command(label="🗑️ 彻底删除", command=self.delete_recycle_file)

        self.recycle_tree.bind('<Button-3>', self.show_recycle_menu)

        self.recycle_folder = os.path.join(TEMP_FOLDER, "recycle_bin")
        self.recycle_index_file = os.path.join(self.recycle_folder, "index.json")
        os.makedirs(self.recycle_folder, exist_ok=True)

        self.recycle_index = self._load_recycle_index()
        
    def create_page3(self):
        """第三页-重复图片页面"""
        self.page3 = ttk.Frame(self.notebook)
        self.notebook.add(self.page3, text="🔄   重复图片")

        header_frame = ttk.Frame(self.page3)
        header_frame.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        title_label = ttk.Label(header_frame, text="🔍 重复图片检测结果", style='Title.TLabel')
        title_label.pack(side=tk.LEFT)

        stats_frame = ttk.Frame(header_frame)
        stats_frame.pack(side=tk.RIGHT)
        
        self.dup_count_label = ttk.Label(stats_frame, text="发现相似组数: 0", 
                                        font=('微软雅黑', 12, 'bold'), foreground='blue')
        self.dup_count_label.pack()

        btn_frame = ttk.Frame(self.page3)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        ttk.Button(btn_frame, text="🔄 刷新列表", 
                  command=self.refresh_duplicate_list, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⚡ 一键处理", 
                  command=self.batch_process_duplicates, width=12).pack(side=tk.LEFT, padx=2)

        main_canvas_frame = ttk.Frame(self.page3)
        main_canvas_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        self.main_canvas = tk.Canvas(main_canvas_frame, bg='#DCDAD5', highlightthickness=0)
        main_scrollbar = ttk.Scrollbar(main_canvas_frame, orient=tk.VERTICAL, command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=main_scrollbar.set)

        self.cards_frame = ttk.Frame(self.main_canvas)
        self.main_canvas.create_window((0, 0), window=self.cards_frame, anchor=tk.NW, width=self.main_canvas.winfo_width())
        
        self.main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        main_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def update_canvas_width(event):
            self.main_canvas.itemconfig(self.main_canvas.find_all()[0], width=event.width)
            self.main_canvas.configure(scrollregion=self.main_canvas.bbox('all'))
        
        self.cards_frame.bind('<Configure>', update_canvas_width)
        self.main_canvas.bind('<Configure>', update_canvas_width)

        self.show_empty_state()
    
    def show_empty_state(self):
        """显示空状态提示"""
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        
        empty_frame = ttk.Frame(self.cards_frame)
        empty_frame.pack(fill=tk.BOTH, expand=True, pady=100)
        
        empty_label = ttk.Label(empty_frame, 
                               text="📁 没有发现相似图片组\n\n"
                                    "请先进行图片扫描和比对",
                               font=('微软雅黑', 14), 
                               foreground='gray',
                               justify=tk.CENTER)
        empty_label.pack()

        tip_label = ttk.Label(empty_frame,
                             text="💡 提示：点击上方'开始扫描图片'和'开始比对重复'按钮",
                             font=('微软雅黑', 10),
                             foreground='green')
        tip_label.pack(pady=20)
        
    def create_page4(self):
        """第四页-设置页面"""
        self.page4 = ttk.Frame(self.notebook)
        self.notebook.add(self.page4, text="⚙️   设置")
        
        title_label = ttk.Label(self.page4, text="系统设置", style='Title.TLabel')
        title_label.pack(pady=20)

        threshold_frame = ttk.LabelFrame(self.page4, text="相似度阈值设置", padding=15)
        threshold_frame.pack(fill=tk.X, padx=20, pady=10)
        
        ttk.Label(threshold_frame, text=f"当前阈值: {SIMILARITY_THRESH}").pack(anchor=tk.W)
        
        self.threshold_var = tk.DoubleVar(value=SIMILARITY_THRESH)

        if RUN_Ver == 1:
            threshold_scale = ttk.Scale(threshold_frame, from_=0.9600, to=0.9963,variable=self.threshold_var, orient=tk.HORIZONTAL, length=1100)
        else:
            threshold_scale = ttk.Scale(threshold_frame, from_=0.3000, to=0.9974,variable=self.threshold_var, orient=tk.HORIZONTAL, length=1100)

        threshold_scale.pack(pady=5)
        
        self.threshold_label = ttk.Label(threshold_frame, text=f"设置值: {SIMILARITY_THRESH}")
        self.threshold_label.pack()
        
        threshold_scale.configure(command=lambda v: self.threshold_label.config(
            text=f"设置值: {float(v):.4f}"))

        other_frame = ttk.LabelFrame(self.page4, text="其他设置", padding=15)
        other_frame.pack(fill=tk.X, padx=20, pady=10)

        self.break_on_error_var = tk.BooleanVar(value=config.get("break_on_error", True))
        ttk.Checkbutton(other_frame, text="出错时立即中断", 
                       variable=self.break_on_error_var).pack(anchor=tk.W, pady=5)
        
        self.print_error_log_var = tk.BooleanVar(value=config.get("print_error_log", True))
        ttk.Checkbutton(other_frame, text="打印错误日志", 
                       variable=self.print_error_log_var).pack(anchor=tk.W, pady=5)

        self.show_delete_confirm_var = tk.BooleanVar(value=config.get("show_delete_confirm", True))
        ttk.Checkbutton(other_frame, text="删除操作前显示确认对话框", 
                       variable=self.show_delete_confirm_var).pack(anchor=tk.W, pady=5)

        system_frame = ttk.LabelFrame(self.page4, text="系统操作", padding=15)
        system_frame.pack(fill=tk.X, padx=20, pady=10)

        system_grid = ttk.Frame(system_frame)
        system_grid.pack(fill=tk.X)

        btn_column = ttk.Frame(system_grid)
        btn_column.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))

        restart_btn = ttk.Button(btn_column, text="🔄   重启软件", 
                                command=self.restart_application, width=15)
        restart_btn.pack(pady=5)

        reset_btn = ttk.Button(btn_column, text="🗑️重置程序", 
                              command=self.reset_application, width=15)
        reset_btn.pack(pady=5)

        desc_column = ttk.Frame(system_grid)
        desc_column.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        restart_desc = ttk.Label(desc_column, text="保存设置更改和数据，之后关闭程序，请手动重启", 
                                font=('微软雅黑', 9), foreground='gray', wraplength=300)
        restart_desc.pack(anchor=tk.W, pady=5)
        
        reset_desc = ttk.Label(desc_column, text="重置程序，同时清除临时文件夹但回收站保留，之后关闭程序", 
                              font=('微软雅黑', 9), foreground='gray', wraplength=300)
        reset_desc.pack(anchor=tk.W, pady=5)

        save_frame = ttk.Frame(self.page4)
        save_frame.pack(pady=20)
        
        save_label = ttk.Label(save_frame, text="💡 设置自动保存，重启生效", 
                              font=('微软雅黑', 10), foreground='green')
        save_label.pack()

        about_frame = ttk.Frame(self.page4)
        about_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=20)
        
        ttk.Button(about_frame, text="关于...", 
                  command=self.show_about_dialog, width=10).pack(side=tk.RIGHT)
        
    def create_status_bar(self):
        """创建状态栏"""
        self.status_bar = ttk.Frame(self.root, relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_label = ttk.Label(self.status_bar, text="就绪")
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.db_status_label = ttk.Label(self.status_bar, text="数据库: 未加载")
        self.db_status_label.pack(side=tk.RIGHT, padx=5)

        self.update_status()
    
    
    def log_message(self, message):
        """添加日志消息"""
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)
        self.log_message("日志已清空")
    
    def update_status(self):
        """更新状态栏"""
        file_count = len(self.db.get("files", {}))
        dup_count = len(self.db.get("duplicates", []))
        self.db_status_label.config(text=f"数据库: {file_count}图片, {dup_count}重复")
        
        if self.scanning:
            self.status_label.config(text="扫描中...")
        elif self.comparing:
            self.status_label.config(text="比对中...")
        else:
            self.status_label.config(text="就绪")
    
    def start_scan(self):
        """开始扫描图片"""
        if self.scanning or self.comparing:
            messagebox.showwarning("警告", "已有任务正在运行")
            return
        
        self.scanning = True
        self.scan_btn.config(state=tk.DISABLED)
        self.compare_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # 创建扫描器
        self.scanner = Scanner(
            self.db,
            progress_callback=self.update_scan_progress,
            log_callback=self.log_message
        )
        
        # 在后台线程中运行扫描
        self.scan_thread = threading.Thread(target=self._run_scan, daemon=True)
        self.scan_thread.start()
    
    def _run_scan(self):
        """运行扫描任务"""
        try:
            success = self.scanner.start_scan()
            if success:
                self.log_message("扫描完成！")
            else:
                self.log_message("扫描被中断或失败")
        except Exception as e:
            self.log_message(f"扫描出错: {str(e)}")
            traceback.print_exc()
        finally:
            self.after_scan()
    
    def after_scan(self):
        """扫描完成后处理"""
        self.scanning = False
        self.scan_btn.config(state=tk.NORMAL)
        self.compare_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.update_status()
        self.refresh_file_list()
    
    def update_scan_progress(self, current, total, message=""):
        """更新扫描进度"""
        def update():
            if total > 0:
                self.scan_progress['value'] = (current / total) * 100
                self.scan_label.config(text=f"扫描进度: {current}/{total} {message}")
            else:
                self.scan_progress['value'] = 0
                self.scan_label.config(text="扫描进度: 等待开始")
        
        self.root.after(0, update)
    
    def start_compare(self):
        """开始比对重复"""
        if self.scanning or self.comparing:
            messagebox.showwarning("警告", "已有任务正在运行")
            return
        
        if not self.db.get("files"):
            messagebox.showwarning("警告", "请先扫描图片")
            return
        
        self.comparing = True
        self.scan_btn.config(state=tk.DISABLED)
        self.compare_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # 获取设置
        use_gpu = USE_GPU_INFERENCE  
        threshold = self.threshold_var.get()
        
        # 创建比对器
        self.comparator = Comparator(
            self.db,
            progress_callback=self.update_compare_progress,
            log_callback=self.log_message,
            use_gpu=use_gpu,
            threshold=threshold
        )
        
        # 在后台线程中运行
        self.compare_thread = threading.Thread(target=self._run_compare, daemon=True)
        self.compare_thread.start()
    
    def _run_compare(self):
        """运行比对任务"""
        try:
            success = self.comparator.start_compare()
            if success:
                self.log_message("比对完成！")
            else:
                self.log_message("比对被中断或失败")
        except Exception as e:
            self.log_message(f"比对出错: {str(e)}")
            traceback.print_exc()
        finally:
            self.after_compare()
    
    def after_compare(self):
        """比对完成后处理"""
        self.comparing = False
        self.scan_btn.config(state=tk.NORMAL)
        self.compare_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.update_status()
        self.refresh_duplicate_list()
    
    def update_compare_progress(self, current, total, message=""):
        """更新比对进度"""
        def update():
            if total > 0:
                self.compare_progress['value'] = (current / total) * 100
                self.compare_label.config(text=f"比对进度: {current}/{total} {message}")
            else:
                self.compare_progress['value'] = 0
                self.compare_label.config(text="比对进度: 等待开始")
        
        self.root.after(0, update)
    
    def stop_processing(self):
        """停止处理"""
        if self.scanning and hasattr(self, 'scanner'):
            self.scanner.stop_scan()
            self.log_message("正在停止扫描，请关闭窗口手动停止")
        
        if self.comparing and hasattr(self, 'comparator'):
            self.comparator.stop_compare()
            self.log_message("正在停止比对，请关闭窗口手动停止")

    
    def refresh_file_list(self):  # ---------已弃用---------
        """刷新文件列表"""
        file_count = len(self.db.get("files", {}))
        processed = self.db.get("scan_processed", 0)

        if hasattr(self, 'total_files_label'):
            self.total_files_label.config(text=f"总图片数: {file_count}")
            self.processed_files_label.config(text=f"已处理数: {processed}")
            self.valid_files_label.config(text=f"有效图片数: {file_count}")
        
        self.log_message(f"文件列表已刷新，共 {file_count} 个文件")
    
    def refresh_duplicate_list(self):
        """刷新重复卡组"""
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        
        duplicate_groups = self.db.get("duplicate_groups", [])
        if not duplicate_groups:
            duplicate_groups = self._generate_groups_from_duplicates()
        
        if not duplicate_groups:
            self.show_empty_state()
            self.dup_count_label.config(text="发现相似组数: 0")
            self.log_message("没有发现相似图片组")
            return

        group_count = len(duplicate_groups)
        total_duplicates = sum(len(group) for group in duplicate_groups)
        self.dup_count_label.config(text=f"发现相似组数: {group_count} (共 {total_duplicates} 张图片)")

        for idx, group in enumerate(duplicate_groups, 1):
            if len(group) >= 2:
                self.create_group_card(idx, group)
        
        self.log_message(f"重复列表已刷新，共 {group_count} 个相似组")
    
    def create_group_card(self, group_number, group_files):
        """创建分组卡片"""
        card_frame = ttk.LabelFrame(self.cards_frame, text=f"第 {group_number} 组 - 共 {len(group_files)} 张相似图片", 
                                   padding=15)
        card_frame.pack(fill=tk.X, padx=5, pady=10, ipadx=5, ipady=5)

        inner_frame = ttk.Frame(card_frame)
        inner_frame.pack(fill=tk.X, expand=True)

        for idx, file_path in enumerate(group_files, 1):
            self.create_image_row(inner_frame, idx, file_path, group_number, len(group_files))
    
    def create_image_row(self, parent_frame, index, file_path, group_number, total_in_group):
        """创建图片行"""
        row_frame = ttk.Frame(parent_frame)
        row_frame.pack(fill=tk.X, pady=5)

        left_frame = ttk.Frame(row_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        idx_label = ttk.Label(left_frame, text=f"{index}.", font=('微软雅黑', 10, 'bold'), width=3)
        idx_label.pack(side=tk.LEFT, padx=(0, 10))

        thumb_frame = ttk.Frame(left_frame)
        thumb_frame.pack(side=tk.LEFT, padx=(0, 15))

        thumb_path = self.db["files"].get(file_path, {}).get("thumb", "")

        try:
            if thumb_path and os.path.exists(thumb_path):
                img = create_thumbnail_image(thumb_path, max_size=(60, 60))
                img_label = ttk.Label(thumb_frame, image=img, cursor="hand2")
                img_label.image = img  
                img_label.pack()
            else:
                img = create_default_thumbnail((60, 60))
                img_label = ttk.Label(thumb_frame, image=img, cursor="hand2")
                img_label.image = img
                img_label.pack()
        except:
            img_label = ttk.Label(thumb_frame, text="📷", width=5, height=3, cursor="hand2")
            img_label.pack()

        img_label.bind('<Button-1>', lambda e, path=file_path: self.open_file(path))

        info_frame = ttk.Frame(left_frame)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        file_name = os.path.basename(file_path)
        if len(file_name) > 40:
            file_name = file_name[:37] + "..."
        
        name_label = ttk.Label(info_frame, text=file_name, font=('微软雅黑', 10), cursor="hand2")
        name_label.pack(anchor=tk.W)

        dir_path = os.path.dirname(file_path)
        if len(dir_path) > 60:
            dir_path = "..." + dir_path[-57:]
        
        path_label = ttk.Label(info_frame, text=dir_path, font=('微软雅黑', 8), foreground='gray')
        path_label.pack(anchor=tk.W)

        try:
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                size_text = format_file_size(file_size)
            else:
                size_text = "文件不存在"
        except:
            size_text = "未知大小"
        
        size_label = ttk.Label(info_frame, text=f"大小: {size_text}", font=('微软雅黑', 8), foreground='blue')
        size_label.pack(anchor=tk.W)
        
        name_label.bind('<Button-1>', lambda e, path=file_path: self.open_file(path))

        btn_frame = ttk.Frame(row_frame)
        btn_frame.pack(side=tk.RIGHT)

        ttk.Button(btn_frame, text="👁️ 查看大图", width=15,
                  command=lambda path=file_path: self.show_image_preview(path, f"第 {group_number} 组 - 图片 {index}")).pack(side=tk.LEFT, padx=3)

        ttk.Button(btn_frame, text="📁 打开文件夹", width=15,
                  command=lambda path=file_path: self.open_file_folder(path)).pack(side=tk.LEFT, padx=3)

        ttk.Button(btn_frame, text="💾 只保留这一张", width=15,
                  command=lambda g=group_number, idx=index, total=total_in_group, path=file_path: 
                  self.keep_only_this_image(g, idx, total, path)).pack(side=tk.LEFT, padx=3)

        ttk.Button(btn_frame, text="🗑️ 删除该张", width=12,
                  command=lambda path=file_path: self.delete_single_image(path)).pack(side=tk.LEFT, padx=3)

        if index < total_in_group:
            separator = ttk.Separator(parent_frame, orient=tk.HORIZONTAL)
            separator.pack(fill=tk.X, pady=5)
    
    def open_file_folder(self, file_path):
        """打开文件所在文件夹"""
        folder_path = os.path.dirname(file_path)
        if os.path.exists(folder_path):
            try:
                if os.name == 'nt': 
                    os.startfile(folder_path)
                elif os.name == 'posix': 
                    subprocess.call(['open', folder_path])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开文件夹: {str(e)}")
        else:
            messagebox.showwarning("警告", "文件夹不存在")
    
    def keep_only_this_image(self, group_number, image_index, total_in_group, file_path):
        """只保留这一张图片，移动组内其他图片到回收站"""
        if self.should_show_delete_confirm():
            if not messagebox.askyesno("确认", 
                                      f"确定要只保留这张图片吗？\n"
                                      f"第 {group_number} 组共 {total_in_group} 张图片，将移动其他 {total_in_group-1} 张到回收站。\n"
                                      f"保留: {os.path.basename(file_path)}"):
                return

        duplicate_groups = self.db.get("duplicate_groups", [])
        if group_number - 1 < len(duplicate_groups):
            group_files = duplicate_groups[group_number - 1]
            
            moved_files = []
            errors = []

            for i, current_path in enumerate(group_files):
                if current_path == file_path:
                    continue  
                
                try:
                    if os.path.exists(current_path):

                        if self.move_to_recycle_bin(current_path):
                            moved_files.append(current_path)
                            

                            if current_path in self.db["files"]:
                                del self.db["files"][current_path]
                        else:
                            errors.append(f"移动到回收站失败: {current_path}")
                    else:
                        errors.append(f"文件不存在: {current_path}")
                except Exception as e:
                    errors.append(f"处理文件失败 {current_path}: {str(e)}")

            duplicate_groups[group_number - 1] = [file_path]

            if len(duplicate_groups[group_number - 1]) <= 1:
                duplicate_groups.pop(group_number - 1)
            
            self.db["duplicate_groups"] = duplicate_groups

            self._update_duplicates_from_groups()

            save_db(self.db)

            self.refresh_file_list()
            self.refresh_duplicate_list()
            self.refresh_recycle_list()
            self.update_status()

            if moved_files:
                self.log_message(f"第 {group_number} 组：已移动 {len(moved_files)} 张图片到回收站，只保留了指定图片")
            if errors:
                for error in errors:
                    self.log_message(f"错误: {error}")
            
            messagebox.showinfo("成功", f"已移动 {len(moved_files)} 张图片到回收站，只保留了指定图片")
    
    def delete_single_image(self, file_path):
        """移动单张图片到回收站"""
        if self.should_show_delete_confirm():
            if not messagebox.askyesno("确认", f"确定要移动这张图片到回收站吗？\n{os.path.basename(file_path)}"):
                return
        
        try:
            if os.path.exists(file_path):
                if self.move_to_recycle_bin(file_path):
                    self.log_message(f"已移动到回收站: {file_path}")
                    
                    if file_path in self.db["files"]:
                        del self.db["files"][file_path]

                    duplicate_groups = self.db.get("duplicate_groups", [])
                    updated_groups = []
                    
                    for group in duplicate_groups:
                        if file_path in group:
                            new_group = [f for f in group if f != file_path]
                            if len(new_group) > 1:  
                                updated_groups.append(new_group)
                        else:
                            updated_groups.append(group)
                    
                    self.db["duplicate_groups"] = updated_groups

                    self._update_duplicates_from_groups()

                    save_db(self.db)

                    self.refresh_file_list()
                    self.refresh_duplicate_list()
                    self.refresh_recycle_list()
                    self.update_status()
                    
                    messagebox.showinfo("成功", "图片已移动到回收站")
                else:
                    messagebox.showerror("错误", "移动到回收站失败")
            else:
                messagebox.showwarning("警告", "文件不存在")
        except Exception as e:
            messagebox.showerror("错误", f"处理文件失败: {str(e)}")
    
    def _generate_groups_from_duplicates(self):
        """旧数据分组"""
        duplicates = self.db.get("duplicates", [])
        if not duplicates:
            return []

        graph = {}
        for dup_pair in duplicates:
            if len(dup_pair) >= 2:
                a, b = dup_pair[0], dup_pair[1]
                if a not in graph:
                    graph[a] = set()
                if b not in graph:
                    graph[b] = set()
                graph[a].add(b)
                graph[b].add(a)
        
        visited = set()
        groups = []
        
        for node in graph:
            if node not in visited:
                stack = [node]
                group = []
                
                while stack:
                    current = stack.pop()
                    if current not in visited:
                        visited.add(current)
                        group.append(current)
                        for neighbor in graph[current]:
                            if neighbor not in visited:
                                stack.append(neighbor)

                group.sort()
                if len(group) > 1:
                    groups.append(group)

        groups.sort(key=len, reverse=True)

        self.db["duplicate_groups"] = groups
        save_db(self.db)
        
        return groups
    
    def on_group_selected(self, event):
        """当选择分组时显示详情"""
        selection = self.dup_tree.selection()
        if not selection:
            return
        
        item = self.dup_tree.item(selection[0])
        values = item['values']
        
        if len(values) >= 1:
            group_index = int(values[0]) - 1  # 转0-based索引
            duplicate_groups = self.db.get("duplicate_groups", [])
            
            if 0 <= group_index < len(duplicate_groups):
                self.show_group_details(duplicate_groups[group_index], group_index + 1)
    
    def show_group_details(self, group_files, group_number):
        """分组详情"""
        for widget in self.detail_inner_frame.winfo_children():
            widget.destroy()
        
        if not group_files or group_number == 0:
            info_frame = ttk.Frame(self.detail_inner_frame)
            info_frame.pack(fill=tk.BOTH, expand=True, pady=50)
            
            info_label = ttk.Label(info_frame, 
                                  text="👈 请在左侧选择一个相似图片分组\n\n"
                                       "选择分组后，这里会显示该组的所有图片缩略图\n"
                                       "点击缩略图可以打开原图",
                                  font=('微软雅黑', 12), 
                                  foreground='gray',
                                  justify=tk.CENTER)
            info_label.pack()

            self.group_info_label.config(text="请从左侧列表中选择一个分组")
            return

        self.group_info_label.config(text=f"第 {group_number} 组 - 共 {len(group_files)} 张相似图片")

        title_label = ttk.Label(self.detail_inner_frame, 
                               text=f"📁 第 {group_number} 组 - 共 {len(group_files)} 张相似图片",
                               font=('微软雅黑', 12, 'bold'),
                               foreground='blue')
        title_label.grid(row=0, column=0, columnspan=4, pady=(0, 15), sticky=tk.W)

        row, col = 1, 0
        max_cols = 4  
        
        for idx, file_path in enumerate(group_files, 1):

            thumb_frame = ttk.Frame(self.detail_inner_frame, relief=tk.RAISED, borderwidth=2)
            thumb_frame.grid(row=row, column=col, padx=8, pady=8, sticky=tk.NSEW)

            thumb_path = self.db["files"].get(file_path, {}).get("thumb", "")

            try:
                if thumb_path and os.path.exists(thumb_path):
                    img = create_thumbnail_image(thumb_path, max_size=(120, 120))
                    img_label = ttk.Label(thumb_frame, image=img, cursor="hand2")
                    img_label.image = img  
                    img_label.pack(padx=8, pady=8)
                else:
                    img = create_default_thumbnail((120, 120))
                    img_label = ttk.Label(thumb_frame, image=img, cursor="hand2")
                    img_label.image = img
                    img_label.pack(padx=8, pady=8)
            except:
                img_label = ttk.Label(thumb_frame, text="📷\n无法加载\n缩略图", 
                                     width=12, height=6, cursor="hand2")
                img_label.pack(padx=8, pady=8)

            file_name = os.path.basename(file_path)
            if len(file_name) > 18:
                file_name = file_name[:15] + "..."
            
            name_frame = ttk.Frame(thumb_frame)
            name_frame.pack(fill=tk.X, pady=(0, 5))

            idx_label = ttk.Label(name_frame, text=f"{idx}.", font=('微软雅黑', 9, 'bold'))
            idx_label.pack(side=tk.LEFT, padx=(5, 2))

            name_label = ttk.Label(name_frame, text=file_name, 
                                  font=('微软雅黑', 9),
                                  wraplength=100, 
                                  justify=tk.CENTER,
                                  cursor="hand2")
            name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def open_image_handler(event, path=file_path):
                self.open_file(path)
            
            thumb_frame.bind('<Button-1>', open_image_handler)
            img_label.bind('<Button-1>', open_image_handler)
            name_label.bind('<Button-1>', open_image_handler)
            idx_label.bind('<Button-1>', open_image_handler)
            
            # 悬停效果
            def on_enter(event):
                event.widget.configure(relief=tk.SUNKEN)
                
            def on_leave(event):
                event.widget.configure(relief=tk.RAISED)
            
            thumb_frame.bind('<Enter>', on_enter)
            thumb_frame.bind('<Leave>', on_leave)
            
            # 更新网格位置
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        
        # 配置网格权重
        for i in range(max_cols):
            self.detail_inner_frame.grid_columnconfigure(i, weight=1, uniform="col")
        
        # 底部提示
        tip_label = ttk.Label(self.detail_inner_frame, 
                             text="💡 提示：点击任意缩略图可打开原图",
                             font=('微软雅黑', 9),
                             foreground='green')
        tip_label.grid(row=row+1, column=0, columnspan=max_cols, pady=(20, 0))
    
    def delete_duplicate_group(self):
        """删除整个分组"""
        selection = self.dup_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个相似分组")
            return
        
        item = self.dup_tree.item(selection[0])
        values = item['values']
        
        if len(values) >= 1:
            group_index = int(values[0]) - 1  # 转0-based索引
            duplicate_groups = self.db.get("duplicate_groups", [])
            
            if 0 <= group_index < len(duplicate_groups):
                group_files = duplicate_groups[group_index]

                if not messagebox.askyesno("确认删除", 
                                          f"确定要删除第 {group_index + 1} 组吗？\n"
                                          f"该组包含 {len(group_files)} 张图片。\n"
                                          f"将删除除第一张外的所有图片。"):
                    return
                
                deleted_files = []
                errors = []

                for i, file_path in enumerate(group_files):
                    if i == 0:
                        continue 
                    
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            deleted_files.append(file_path)

                            if file_path in self.db["files"]:
                                del self.db["files"][file_path]
                        else:
                            errors.append(f"文件不存在: {file_path}")
                    except Exception as e:
                        errors.append(f"删除文件失败 {file_path}: {str(e)}")

                duplicate_groups.pop(group_index)
                self.db["duplicate_groups"] = duplicate_groups

                self._update_duplicates_from_groups()

                save_db(self.db)

                self.refresh_file_list()
                self.refresh_duplicate_list()
                self.update_status()

                if deleted_files:
                    self.log_message(f"已删除分组 {group_index + 1}，删除了 {len(deleted_files)} 张图片")
                if errors:
                    for error in errors:
                        self.log_message(f"错误: {error}")
                
                messagebox.showinfo("成功", f"已删除分组，删除了 {len(deleted_files)} 张图片")
    
    def _update_duplicates_from_groups(self): 
        """从分组数据更新对列表"""
        duplicate_groups = self.db.get("duplicate_groups", [])
        duplicates = []
        
        for group in duplicate_groups:
            if len(group) >= 2:
                # 为每组生成图片对
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        duplicates.append([group[i], group[j]])
        
        self.db["duplicates"] = duplicates
    
    def view_duplicate_detail(self):#--------------已弃用--------------
        """查看重复详情"""
        selection = self.dup_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个重复对")
            return
        
        item = self.dup_tree.item(selection[0])
        values = item['values']
        
        if len(values) >= 3:
            file_a = values[1]
            file_b = values[2]
            
            detail_window = tk.Toplevel(self.root)
            detail_window.title("重复详情")
            detail_window.geometry("800x600")
            
            frame = ttk.Frame(detail_window)
            frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            frame_a = ttk.LabelFrame(frame, text="图片A", padding=10)
            frame_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            
            try:
                img_a = create_thumbnail_image(file_a, max_size=(300, 300))
                label_a = ttk.Label(frame_a, image=img_a)
                label_a.image = img_a
                label_a.pack()
            except:
                label_a = ttk.Label(frame_a, text="无法加载图片")
                label_a.pack()
            
            label_a_path = ttk.Label(frame_a, text=f"路径: {file_a}", wraplength=350)
            label_a_path.pack(pady=5)

            frame_b = ttk.LabelFrame(frame, text="图片B", padding=10)
            frame_b.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
            
            try:
                img_b = create_thumbnail_image(file_b, max_size=(300, 300))
                label_b = ttk.Label(frame_b, image=img_b)
                label_b.image = img_b
                label_b.pack()
            except:
                label_b = ttk.Label(frame_b, text="无法加载图片")
                label_b.pack()
            
            label_b_path = ttk.Label(frame_b, text=f"路径: {file_b}", wraplength=350)
            label_b_path.pack(pady=5)

            btn_frame = ttk.Frame(detail_window)
            btn_frame.pack(pady=10)
            
            ttk.Button(btn_frame, text="打开图片A", 
                      command=lambda: self.open_file(file_a)).grid(row=0, column=0, padx=5)
            ttk.Button(btn_frame, text="打开图片B", 
                      command=lambda: self.open_file(file_b)).grid(row=0, column=1, padx=5)
            ttk.Button(btn_frame, text="删除图片A", 
                      command=lambda: self.delete_single_file(file_a, detail_window)).grid(row=0, column=2, padx=5)
            ttk.Button(btn_frame, text="删除图片B", 
                      command=lambda: self.delete_single_file(file_b, detail_window)).grid(row=0, column=3, padx=5)
    
    def open_file(self, file_path):
        """打开文件"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(file_path)
            elif os.name == 'posix':  # macOS/Linux
                subprocess.call(['open', file_path])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件: {str(e)}")
    
    def delete_single_file(self, file_path, parent_window=None):
        """删除单个文件"""
        if not messagebox.askyesno("确认", f"确定要删除文件吗？\n{file_path}"):
            return
        
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.log_message(f"已删除文件: {file_path}")

                if file_path in self.db["files"]:
                    del self.db["files"][file_path]
                    save_db(self.db)

                self.refresh_file_list()
                self.refresh_duplicate_list()
                self.update_status()
                
                messagebox.showinfo("成功", "文件已删除", parent=parent_window)
                if parent_window:
                    parent_window.destroy()
            else:
                messagebox.showwarning("警告", "文件不存在", parent=parent_window)
        except Exception as e:
            messagebox.showerror("错误", f"删除文件失败: {str(e)}", parent=parent_window)
    
    def view_selected_image(self):#--------------已弃用--------------
        """查看选中图片的大图"""
        selection = self.dup_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个分组")
            return
        
        item = self.dup_tree.item(selection[0])
        values = item['values']
        
        if len(values) >= 1:
            group_index = int(values[0]) - 1
            duplicate_groups = self.db.get("duplicate_groups", [])
            
            if 0 <= group_index < len(duplicate_groups):
                group_files = duplicate_groups[group_index]
                if group_files:
                    # 显示第一张图片的大图
                    self.show_image_preview(group_files[0], f"第 {group_index + 1} 组 - 图片预览")
    
    def open_selected_folder(self):#--------------已弃用--------------
        """打开选中图片所在的文件夹"""
        selection = self.dup_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个分组")
            return
        
        item = self.dup_tree.item(selection[0])
        values = item['values']
        
        if len(values) >= 1:
            group_index = int(values[0]) - 1
            duplicate_groups = self.db.get("duplicate_groups", [])
            
            if 0 <= group_index < len(duplicate_groups):
                group_files = duplicate_groups[group_index]
                if group_files:
                    file_path = group_files[0]
                    folder_path = os.path.dirname(file_path)
                    if os.path.exists(folder_path):
                        try:
                            if os.name == 'nt':  # Windows
                                os.startfile(folder_path)
                            elif os.name == 'posix':  # macOS/Linux
                                subprocess.call(['open', folder_path])
                        except Exception as e:
                            messagebox.showerror("错误", f"无法打开文件夹: {str(e)}")
                    else:
                        messagebox.showwarning("警告", "文件夹不存在")
    
    def show_image_preview(self, image_path, title="图片预览"):
        """显示图片预览窗口"""
        try:
            if not os.path.exists(image_path):
                thumb_path = self.db["files"].get(image_path, {}).get("thumb", "")
                if thumb_path and os.path.exists(thumb_path):
                    show_preview(self.root, thumb_path, f"{title} (缩略图)")
                    return
                else:
                    messagebox.showwarning("警告", "图片文件不存在")
                    return
            
            show_preview(self.root, image_path, title)
        except Exception as e:
            messagebox.showerror("错误", f"无法预览图片: {str(e)}")
    
    def delete_duplicate(self):
        """删除重复"""
        selection = self.dup_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个重复对")
            return
        
        item = self.dup_tree.item(selection[0])
        values = item['values']
        
        if len(values) >= 1:
            dup_index = int(values[0]) - 1  # 转0-b索引
            
            success, result = delete_duplicate_files(self.db, dup_index)
            if success:
                self.log_message(f"已删除重复对: {result['deleted']}")
                if result['errors']:
                    for error in result['errors']:
                        self.log_message(f"错误: {error}")
                
                self.refresh_file_list()
                self.refresh_duplicate_list()
                self.update_status()
                
                messagebox.showinfo("成功", "重复文件已删除")
            else:
                messagebox.showerror("错误", result)
    
    def batch_process_duplicates(self):
        """一键处理所有重复"""
        duplicate_groups = self.db.get("duplicate_groups", [])
        if not duplicate_groups:
            messagebox.showwarning("警告", "没有发现重复图片组")
            return

        total_groups = len(duplicate_groups)
        total_files = sum(len(group) for group in duplicate_groups)
        files_to_move = total_files - total_groups 
        
        if self.should_show_delete_confirm():
            if not messagebox.askyesno("确认一键处理", 
                                      f"确定要一键处理所有重复图片组吗？\n"
                                      f"共 {total_groups} 个相似组，{total_files} 张图片。\n"
                                      f"将移动 {files_to_move} 张图片到回收站，每组只保留第一张。\n\n"
                                      f"此操作可能需要一些时间，请耐心等待..."):
                return
        
        progress_dialog = ProgressDialog(self.root, "一键处理进度", f"准备处理 {total_groups} 个相似组...")

        def process_in_background():
            moved_files = []
            errors = []
            
            try:
                for group_idx, group in enumerate(duplicate_groups, 1):
                    if len(group) >= 2:

                        for i, file_path in enumerate(group):
                            if i == 0:
                                continue  
                            
                            try:
                                if os.path.exists(file_path):

                                    if self.move_to_recycle_bin(file_path):
                                        moved_files.append(file_path)
                                       
                                        if file_path in self.db["files"]:
                                            del self.db["files"][file_path]
                                    else:
                                        errors.append(f"移动到回收站失败: {file_path}")
                                else:
                                    errors.append(f"文件不存在: {file_path}")
                            except Exception as e:
                                errors.append(f"处理文件失败 {file_path}: {str(e)}")
                    
                   
                    progress_dialog.update_message(f"处理第 {group_idx}/{total_groups} 组")

                    time.sleep(0.1)  

                new_groups = []
                for group in duplicate_groups:
                    if len(group) >= 2:
                        new_groups.append([group[0]])  
                
                self.db["duplicate_groups"] = new_groups

                self._update_duplicates_from_groups()

                save_db(self.db)

                progress_dialog.close()

                def update_ui():
                    self.refresh_file_list()
                    self.refresh_duplicate_list()
                    self.refresh_recycle_list()
                    self.update_status()

                    if moved_files:
                        self.log_message(f"一键处理完成：已移动 {len(moved_files)} 张图片到回收站")
                    if errors:
                        for error in errors:
                            self.log_message(f"错误: {error}")

                    if not self.db.get("duplicate_groups", []):
                        self.show_empty_state()
                        self.dup_count_label.config(text="发现相似组数: 0")
                    
                    messagebox.showinfo("完成", f"一键处理完成！\n"
                                              f"已移动 {len(moved_files)} 张图片到回收站\n"
                                              f"每组只保留了第一张图片")
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                progress_dialog.close()
                error_msg = str(e) 
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("错误", f"一键处理失败: {msg}"))

        threading.Thread(target=process_in_background, daemon=True).start()
    
    def export_results(self):#--------------已弃用--------------
        """导出结果"""
        if not self.db.get("files"):
            messagebox.showwarning("警告", "没有数据可导出")
            return

        export_window = tk.Toplevel(self.root)
        export_window.title("导出结果")
        export_window.geometry("400x300")
        
        ttk.Label(export_window, text="选择导出格式:", font=('微软雅黑', 12)).pack(pady=20)
        
        format_var = tk.StringVar(value="json")
        
        ttk.Radiobutton(export_window, text="JSON格式", 
                       variable=format_var, value="json").pack(pady=5)
        ttk.Radiobutton(export_window, text="CSV格式", 
                       variable=format_var, value="csv").pack(pady=5)
        
        ttk.Label(export_window, text="导出路径:").pack(pady=10)
        
        path_var = tk.StringVar(value=os.path.join(TEMP_FOLDER, "results"))
        path_entry = ttk.Entry(export_window, textvariable=path_var, width=40)
        path_entry.pack(pady=5)
        
        def browse_path():
            file_path = filedialog.asksaveasfilename(
                initialdir=os.path.dirname(path_var.get()),
                initialfile=os.path.basename(path_var.get()),
                defaultextension=f".{format_var.get()}",
                filetypes=[(f"{format_var.get().upper()}文件", f"*.{format_var.get()}")]
            )
            if file_path:
                path_var.set(file_path)
        
        ttk.Button(export_window, text="浏览...", command=browse_path).pack(pady=5)
        
        def do_export():
            format_type = format_var.get()
            output_path = path_var.get()
            
            try:
                if format_type == "json":
                    result_path = export_results_to_json(self.db, output_path)
                else:  # csv
                    result_path = export_results_to_csv(self.db, output_path)
                
                self.log_message(f"结果已导出到: {result_path}")
                messagebox.showinfo("成功", f"结果已导出到:\n{result_path}", parent=export_window)
                export_window.destroy()
                
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {str(e)}", parent=export_window)
        
        ttk.Button(export_window, text="导出", command=do_export).pack(pady=20)
    
    # ===================== 回收站功能方法 =====================
    
    def refresh_recycle_list(self):
        """刷新回收站列表"""
        for item in self.recycle_tree.get_children():
            self.recycle_tree.delete(item)

        recycle_files = []
        total_size = 0

        self.recycle_index = self._load_recycle_index()
        
        for idx, entry in enumerate(self.recycle_index, 1):
            recycle_path = entry.get('recycle_path', '')
            original_path = entry.get('original_path', '')
            delete_time = entry.get('delete_time', '')
            filename = entry.get('filename', '')
            
            if os.path.exists(recycle_path):
                file_size = os.path.getsize(recycle_path)
                total_size += file_size

                recycle_files.append({
                    'index': idx,
                    'original_path': original_path,
                    'delete_time': delete_time,
                    'size': format_file_size(file_size),
                    'file_path': recycle_path,
                    'filename': filename
                })
            else:

                self._remove_from_recycle_index(recycle_path)

        self.recycle_count_label.config(text=f"回收站文件数: {len(recycle_files)}")
        self.recycle_size_label.config(text=f"总大小: {format_file_size(total_size)}")

        for file_info in recycle_files:
            self.recycle_tree.insert('', 'end', values=(
                file_info['index'],
                file_info['original_path'],
                file_info['delete_time'],
                file_info['size']
            ), tags=(file_info['file_path'],))
        
        self.log_message(f"回收站列表已刷新，共 {len(recycle_files)} 个文件")
    
    def show_recycle_menu(self, event):
        """显示回收站右键菜单"""
        item = self.recycle_tree.identify_row(event.y)
        if item:
            self.recycle_tree.selection_set(item)
            self.recycle_menu.post(event.x_root, event.y_root)
    
    def view_recycle_image(self):
        """查看回收站图片的大图"""
        selection = self.recycle_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        item = self.recycle_tree.item(selection[0])
        tags = item['tags']
        if tags:
            file_path = tags[0]
            if os.path.exists(file_path):
                self.show_image_preview(file_path, "回收站图片预览")
            else:
                messagebox.showwarning("警告", "文件不存在")
    
    def open_recycle_file_location(self):
        """打开回收站文件位置"""
        selection = self.recycle_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        item = self.recycle_tree.item(selection[0])
        tags = item['tags']
        if tags:
            file_path = tags[0]
            folder_path = os.path.dirname(file_path)
            if os.path.exists(folder_path):
                try:
                    if os.name == 'nt':  # Windows
                        os.startfile(folder_path)
                    elif os.name == 'posix':  # macOS/Linux
                        subprocess.call(['open', folder_path])
                except Exception as e:
                    messagebox.showerror("错误", f"无法打开文件夹: {str(e)}")
            else:
                messagebox.showwarning("警告", "文件夹不存在")
    
    def restore_recycle_file(self):
        """还原回收站文件"""
        selection = self.recycle_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        item = self.recycle_tree.item(selection[0])
        tags = item['tags']
        if not tags:
            return
        
        file_path = tags[0]
        filename = os.path.basename(file_path)

        original_path = filename
        if "_from_" in filename:
            parts = filename.split("_from_")
            if len(parts) > 1:
                original_path = parts[1]

        restore_window = tk.Toplevel(self.root)
        restore_window.title("还原文件")
        restore_window.geometry("500x300")

        location_var = tk.StringVar(value="original")
        
        ttk.Label(restore_window, text="选择还原位置:", font=('微软雅黑', 12)).pack(pady=10)
        
        location_frame = ttk.Frame(restore_window)
        location_frame.pack(pady=5)
        
        ttk.Radiobutton(location_frame, text="原位置", 
                       variable=location_var, value="original").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(location_frame, text="指定位置", 
                       variable=location_var, value="custom").pack(side=tk.LEFT, padx=10)

        original_frame = ttk.LabelFrame(restore_window, text="原位置信息", padding=10)
        original_frame.pack(fill=tk.X, padx=20, pady=10)
        
        ttk.Label(original_frame, text=f"原路径: {original_path}", wraplength=450).pack(anchor=tk.W)

        custom_frame = ttk.LabelFrame(restore_window, text="指定位置", padding=10)
        
        custom_path_var = tk.StringVar(value=os.path.dirname(os.path.abspath(__file__)))
        custom_entry = ttk.Entry(custom_frame, textvariable=custom_path_var, width=50)
        custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_custom_path():
            folder_path = filedialog.askdirectory(
                initialdir=custom_path_var.get(),
                title="选择还原文件夹"
            )
            if folder_path:
                custom_path_var.set(folder_path)
        
        ttk.Button(custom_frame, text="浏览...", command=browse_custom_path).pack(side=tk.RIGHT)

        custom_frame.pack_forget()
        
        def toggle_custom_path():
            if location_var.get() == "custom":
                custom_frame.pack(fill=tk.X, padx=20, pady=10)
            else:
                custom_frame.pack_forget()
        
        location_var.trace('w', lambda *args: toggle_custom_path())

        def do_restore():
            if location_var.get() == "original":
                target_path = original_path
            else:
                custom_path = custom_path_var.get()
                if not custom_path:
                    messagebox.showwarning("警告", "请指定还原路径", parent=restore_window)
                    return

                target_path = os.path.join(custom_path, os.path.basename(original_path))

            if self.should_show_delete_confirm():
                if not messagebox.askyesno("确认", f"确定要还原文件到以下位置吗？\n{target_path}", parent=restore_window):
                    return
            
            try:
                if os.path.exists(target_path):
                    if not messagebox.askyesno("确认", f"目标路径已存在文件:\n{target_path}\n是否覆盖？", parent=restore_window):
                        return
                
                shutil.move(file_path, target_path)
                
                self.log_message(f"已还原文件: {filename} -> {target_path}")

                self.refresh_recycle_list()
                
                restore_window.destroy()
                messagebox.showinfo("成功", "文件已还原")
                
            except Exception as e:
                messagebox.showerror("错误", f"还原文件失败: {str(e)}", parent=restore_window)
        
        btn_frame = ttk.Frame(restore_window)
        btn_frame.pack(pady=20)
        
        ttk.Button(btn_frame, text="还原", command=do_restore, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=restore_window.destroy, width=15).pack(side=tk.LEFT, padx=10)

        restore_window.update_idletasks()
        width = restore_window.winfo_width()
        height = restore_window.winfo_height()
        x = (restore_window.winfo_screenwidth() // 2) - (width // 2)
        y = (restore_window.winfo_screenheight() // 2) - (height // 2)
        restore_window.geometry(f'{width}x{height}+{x}+{y}')

        restore_window.transient(self.root)
        restore_window.grab_set()
        self.root.wait_window(restore_window)
    
    def delete_recycle_file(self):
        """彻底删除回收站文件"""
        selection = self.recycle_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        item = self.recycle_tree.item(selection[0])
        tags = item['tags']
        if not tags:
            return
        
        file_path = tags[0]

        if not messagebox.askyesno("确认", f"确定要彻底删除这个文件吗？\n此操作不可恢复！"):
            return
        
        try:
            os.remove(file_path)
            self.log_message(f"已彻底删除文件: {file_path}")

            self.refresh_recycle_list()
            
            messagebox.showinfo("成功", "文件已彻底删除")
            
        except Exception as e:
            messagebox.showerror("错误", f"删除文件失败: {str(e)}")
    
    def open_recycle_folder(self):
        """打开回收站文件夹"""
        if os.path.exists(self.recycle_folder):
            try:
                if os.name == 'nt':  # Windows
                    os.startfile(self.recycle_folder)
                elif os.name == 'posix':  # macOS/Linux
                    subprocess.call(['open', self.recycle_folder])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开文件夹: {str(e)}")
        else:
            messagebox.showwarning("警告", "回收站文件夹不存在")
    
    def delete_all_recycle_files(self):
        """全部彻底删除"""
        if not messagebox.askyesno("确认", "确定要彻底删除回收站中的所有文件吗？\n此操作不可恢复！"):
            return
        
        try:
            deleted_count = 0
            if os.path.exists(self.recycle_folder):
                for filename in os.listdir(self.recycle_folder):
                    file_path = os.path.join(self.recycle_folder, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_count += 1
            
            self.log_message(f"已彻底删除 {deleted_count} 个回收站文件")

            self.refresh_recycle_list()
            
            messagebox.showinfo("成功", f"已彻底删除 {deleted_count} 个文件")
            
        except Exception as e:
            messagebox.showerror("错误", f"删除文件失败: {str(e)}")
    
    def restore_all_recycle_files(self):
        """全部还原"""
        restore_window = tk.Toplevel(self.root)
        restore_window.title("全部还原")
        restore_window.geometry("500x300")

        location_var = tk.StringVar(value="original")
        
        ttk.Label(restore_window, text="选择还原位置:", font=('微软雅黑', 12)).pack(pady=10)
        
        location_frame = ttk.Frame(restore_window)
        location_frame.pack(pady=5)
        
        ttk.Radiobutton(location_frame, text="原位置", 
                       variable=location_var, value="original").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(location_frame, text="指定位置", 
                       variable=location_var, value="custom").pack(side=tk.LEFT, padx=10)

        custom_frame = ttk.LabelFrame(restore_window, text="指定位置", padding=10)
        custom_frame.pack(fill=tk.X, padx=20, pady=10)
        
        custom_path_var = tk.StringVar(value=os.path.dirname(os.path.abspath(__file__)))
        custom_entry = ttk.Entry(custom_frame, textvariable=custom_path_var, width=50)
        custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_custom_path():
            folder_path = filedialog.askdirectory(
                initialdir=custom_path_var.get(),
                title="选择还原文件夹"
            )
            if folder_path:
                custom_path_var.set(folder_path)
        
        ttk.Button(custom_frame, text="浏览...", command=browse_custom_path).pack(side=tk.RIGHT)

        custom_frame.pack_forget()
        
        def toggle_custom_path():
            if location_var.get() == "custom":
                custom_frame.pack(fill=tk.X, padx=20, pady=10)
            else:
                custom_frame.pack_forget()
        
        location_var.trace('w', lambda *args: toggle_custom_path())

        def do_restore_all():
            if location_var.get() == "custom":
                custom_path = custom_path_var.get()
                if not custom_path:
                    messagebox.showwarning("警告", "请指定还原路径", parent=restore_window)
                    return

            if not messagebox.askyesno("确认", "确定要还原回收站中的所有文件吗？", parent=restore_window):
                return
            
            try:
                restored_count = 0
                errors = []
                
                if os.path.exists(self.recycle_folder):
                    for filename in os.listdir(self.recycle_folder):
                        file_path = os.path.join(self.recycle_folder, filename)
                        
                        # 跳过索引文件
                        if filename == "index.json":
                            continue
                        
                        if os.path.isfile(file_path):
                            # 从索引表中获取原路径
                            original_path = self._get_original_path_from_index(file_path)
                            if not original_path:
                                # 如果索引表中没有，尝试从文件名中提取 #--------------已弃用--------------
                                original_path = filename
                                if "_from_" in filename:
                                    parts = filename.split("_from_")
                                    if len(parts) > 1:
                                        original_path = parts[1]
                            
                            # 确定目标路径
                            if location_var.get() == "original":
                                target_path = original_path
                            else:
                                target_path = os.path.join(custom_path, os.path.basename(original_path))
                            
                            try:
                                if os.path.exists(target_path):

                                    errors.append(f"文件已存在: {target_path}")
                                    continue
                                
                                shutil.move(file_path, target_path)
                                restored_count += 1
                                
                            except Exception as e:
                                errors.append(f"还原失败 {filename}: {str(e)}")
                
                if restored_count > 0:
                    self.log_message(f"已还原 {restored_count} 个文件")
                if errors:
                    for error in errors:
                        self.log_message(f"错误: {error}")
                
                self.refresh_recycle_list()
                
                restore_window.destroy()
                
                result_msg = f"已还原 {restored_count} 个文件"
                if errors:
                    result_msg += f"，{len(errors)} 个文件还原失败"
                
                messagebox.showinfo("完成", result_msg)
                
            except Exception as e:
                messagebox.showerror("错误", f"还原文件失败: {str(e)}", parent=restore_window)
        
        btn_frame = ttk.Frame(restore_window)
        btn_frame.pack(pady=20)
        
        ttk.Button(btn_frame, text="全部还原", command=do_restore_all, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=restore_window.destroy, width=15).pack(side=tk.LEFT, padx=10)

        restore_window.update_idletasks()
        width = restore_window.winfo_width()
        height = restore_window.winfo_height()
        x = (restore_window.winfo_screenwidth() // 2) - (width // 2)
        y = (restore_window.winfo_screenheight() // 2) - (height // 2)
        restore_window.geometry(f'{width}x{height}+{x}+{y}')

        restore_window.transient(self.root)
        restore_window.grab_set()
        self.root.wait_window(restore_window)
    
    def move_to_recycle_bin(self, file_path):
        """移动文件到回收站"""
        if not os.path.exists(file_path):
            return False
        
        try:
            delete_time = datetime.now()

            original_filename = os.path.basename(file_path)
            name, ext = os.path.splitext(original_filename)

            counter = 1
            new_filename = f"{name}{ext}"
            new_path = os.path.join(self.recycle_folder, new_filename)
            
            while os.path.exists(new_path):
                new_filename = f"{name}_{counter}{ext}"
                new_path = os.path.join(self.recycle_folder, new_filename)
                counter += 1

            shutil.move(file_path, new_path)

            self._add_to_recycle_index(file_path, new_path, delete_time)
            
            self.log_message(f"已移动到回收站: {file_path}")
            return True
            
        except Exception as e:
            self.log_message(f"移动到回收站失败 {file_path}: {str(e)}")
            return False
    
    def save_settings(self):
        """保存设置"""
        new_threshold = self.threshold_var.get()

        global SIMILARITY_THRESH
        SIMILARITY_THRESH = new_threshold
        
        self.log_message(f"设置已保存: 阈值={new_threshold:.4f}")
        messagebox.showinfo("成功", "设置已保存，重启后生效")
        
        # 保存到配置文件
        config_path = os.path.join(TEMP_FOLDER, "config.json")
        config = {
            "similarity_threshold": new_threshold,
            "break_on_error": self.break_on_error_var.get(),
            "print_error_log": self.print_error_log_var.get(),
            "show_delete_confirm": self.show_delete_confirm_var.get()
        }
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def should_show_delete_confirm(self):
        return self.show_delete_confirm_var.get()

    
    def _load_recycle_index(self):
        """加载回收站索引表"""
        if os.path.exists(self.recycle_index_file):
            try:
                with open(self.recycle_index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_recycle_index(self):
        """保存回收站索引表"""
        try:
            with open(self.recycle_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.recycle_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_message(f"保存回收站索引表失败: {str(e)}")
    
    def _add_to_recycle_index(self, original_path, recycle_path, delete_time):
        """添加到回收站索引表"""
        index_entry = {
            'original_path': original_path,
            'recycle_path': recycle_path,
            'delete_time': delete_time.strftime("%Y-%m-%d %H:%M:%S"),
            'filename': os.path.basename(recycle_path)
        }
        self.recycle_index.append(index_entry)
        self._save_recycle_index()
    
    def _remove_from_recycle_index(self, recycle_path):
        """从回收站索引表中移除"""
        self.recycle_index = [entry for entry in self.recycle_index 
                             if entry['recycle_path'] != recycle_path]
        self._save_recycle_index()
    
    def _get_original_path_from_index(self, recycle_path):
        """从索引表中获取原路径"""
        for entry in self.recycle_index:
            if entry['recycle_path'] == recycle_path:
                return entry['original_path']
        return None

    
    def update_system_resources(self):
        """更新系统资源显示（磁盘使用率改为读写速率）"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            resources_text = f"[CPU使用率:{cpu_percent:.0f}%]    [内存使用率:{memory_percent:.0f}%]"

            self.system_resources_label.config(text=resources_text)
            
            self.root.after(2000, self.update_system_resources)
            
        except ImportError:
            pass
        except Exception as e:

            self.system_resources_label.config(text=f"获取系统资源失败: {str(e)}")
            self.root.after(5000, self.update_system_resources)
    
    
    def restart_application(self):
        """重启应用程序"""
        if messagebox.askyesno("确认重启", "确定要重启应用程序吗？\n当前设置和数据将保留。"):
            self.log_message("正在重启应用程序...")

            self.save_settings()
            
            self.root.after(1000, self._do_restart)
    
    def _do_restart(self):
        """重启"""
        try:
            # os.startfile(sys.argv[0])
            sys.exit(0)

        except Exception as e:
            messagebox.showerror("重启失败", str(e))
    
    def reset_application(self):
        """重置程序"""
        if messagebox.askyesno("确认重置", "确定要重置程序吗？\n"
                                        "将清除临时文件夹（回收站除外）并重启程序。\n"
                                        "此操作不可恢复！"):
            self.log_message("正在重置程序...")
            
            try:

                if os.path.exists(TEMP_FOLDER):
                    for item in os.listdir(TEMP_FOLDER):
                        item_path = os.path.join(TEMP_FOLDER, item)
                        if item != "recycle_bin":  # 保留回收站
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                
                self.log_message("临时文件夹已清除")

                self.root.after(1000, self._do_restart)
                
            except Exception as e:
                messagebox.showerror("错误", f"重置失败: {str(e)}")
    
    def show_easter_egg(self):
        """彩蛋"""
        egg_window = tk.Toplevel(self.root)
        egg_window.title("彩蛋")

        egg_window.overrideredirect(True)  
        egg_window.attributes('-alpha', 0.9) 
        egg_window.attributes('-topmost', True) 

        screen_width = egg_window.winfo_screenwidth()
        screen_height = egg_window.winfo_screenheight()
        window_width = screen_width
        window_height = 120 

        start_x = -window_width
        start_y = 0  
        
        egg_window.geometry(f"{window_width}x{window_height}+{start_x}+{start_y}")
        
        egg_window.configure(bg='black')
        
        egg_label = tk.Label(
            egg_window,
            text="感谢使用图片查重工具",
            font=('微软雅黑', 64, 'bold'),  
            fg='yellow',
            bg='black'
        )
        egg_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        try:
            egg_window.wm_attributes("-transparentcolor", "black")
            egg_label.configure(bg='black')
        except:
            pass

        animation_duration = 6000  # 5秒
        frames = 100  # 100帧
        frame_delay = animation_duration // frames 

        screen_center_x = screen_width // 2
        end_x = screen_width + window_width  

        def animate(frame):
            if frame <= frames // 2:
                progress = frame / (frames // 2)
                current_x = start_x + (screen_center_x - start_x) * progress
            else:
                progress = (frame - frames // 2) / (frames // 2)
                current_x = screen_center_x + (end_x - screen_center_x) * progress

            egg_window.geometry(f"{window_width}x{window_height}+{int(current_x)}+{start_y}")
            
            if frame < frames:
                egg_window.after(frame_delay, lambda: animate(frame + 1))
            else:
                egg_window.destroy()
        
        def close_on_click(event):
            egg_window.destroy()
        
        egg_window.bind('<Button-1>', close_on_click)
        egg_label.bind('<Button-1>', close_on_click)

        egg_window.update()

        egg_window.after(100, lambda: animate(0))
    

    def show_about_dialog(self):
        """显示关于对话框"""

        self.show_easter_egg()
        play_system_sound("Alarm02")
        about_window = tk.Toplevel(self.root)
        about_window.title("关于")
        about_window.geometry("500x600")
        
        try:
            icon_path = get_resource_path("icon.png")
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(file=icon_path)
                about_window.iconphoto(True, icon)
                about_window.icon_image = icon
        except:
            pass

        main_frame = ttk.Frame(about_window, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        try:
            avatar_path = get_resource_path("icon.png")
            if os.path.exists(avatar_path):
                img = Image.open(avatar_path)
                img = img.resize((120, 120), Image.Resampling.LANCZOS)
                avatar_img = ImageTk.PhotoImage(img)
                avatar_label = ttk.Label(main_frame, image=avatar_img)
                avatar_label.image = avatar_img  
                avatar_label.pack(pady=(0, 20))
            else:
                avatar_label = ttk.Label(main_frame, text="👤", font=('微软雅黑', 48))
                avatar_label.pack(pady=(0, 20))
        except Exception as e:
            avatar_label = ttk.Label(main_frame, text="👤", font=('微软雅黑', 48))
            avatar_label.pack(pady=(0, 20))

        author_frame = ttk.Frame(main_frame)
        author_frame.pack(pady=(0, 10))    
        try:
            small_icon_path = get_resource_path("tz.png")
            if os.path.exists(small_icon_path):
                small_img = Image.open(small_icon_path)
                small_img = small_img.resize((32, 32), Image.Resampling.LANCZOS)
                small_icon_img = ImageTk.PhotoImage(small_img)
                small_icon_label = ttk.Label(author_frame, image=small_icon_img)
                small_icon_label.image = small_icon_img  
                small_icon_label.pack(side=tk.LEFT, padx=(0, 10))
        except:
            pass
        
        author_label = ttk.Label(author_frame, text="作者：HLBQ",font=('微软雅黑', 18, 'bold'))
        author_label.pack(side=tk.LEFT)

        version_label = ttk.Label(main_frame, text="版本: 1.0.0",font=('微软雅黑', 12))
        version_label.pack(pady=(0, 5))

        time_label = ttk.Label(main_frame, text="制作时间: 2026年2月", font=('微软雅黑', 12))
        time_label.pack(pady=(0, 5))

        copyright_label = ttk.Label(main_frame, text="© 版权所有", font=('微软雅黑', 12))
        copyright_label.pack(pady=(0, 5))

        license_frame = ttk.LabelFrame(main_frame, text="协议", padding=10)
        license_frame.pack(fill=tk.X, pady=10)
        
        license_text = scrolledtext.ScrolledText(license_frame, height=6, width=50)
        license_text.pack(fill=tk.BOTH, expand=True)
        license_text.insert(tk.END, "MIT 许可证\n\n")
        license_text.insert(tk.END, "特此免费授予任何获得本软件副本和相关文档文件（以下简称\"软件\"）的人不受限制地处理本软件的权利，包括但不限于使用、复制、修改、合并、发布、分发、再许可和/或销售本软件的副本，以及允许向其提供本软件的人这样做，但须符合以下条件：\n\n")
        license_text.insert(tk.END, "上述版权声明和本许可声明应包含在本软件的所有副本或重要部分中。")

        notice_frame = ttk.LabelFrame(main_frame, text="声明", padding=10)
        notice_frame.pack(fill=tk.X, pady=10)
        
        notice_text = scrolledtext.ScrolledText(notice_frame, height=4, width=50)
        notice_text.pack(fill=tk.BOTH, expand=True)
        notice_text.insert(tk.END, "本软件按\"原样\"提供，不提供任何形式的明示或暗示保证，包括但不限于对适销性、特定用途适用性和非侵权性的保证。在任何情况下，作者或版权持有人均不对因使用本软件或本软件的其他处理而导致的任何索赔、损害或其他责任负责。")
        notice_text.configure(state=tk.DISABLED)

        close_btn = ttk.Button(main_frame, text="关闭",command=about_window.destroy, width=15)
        close_btn.pack(pady=20)

        about_window.update_idletasks()
        width = about_window.winfo_width()
        height = about_window.winfo_height()
        x = (about_window.winfo_screenwidth() // 2) - (width // 2)
        y = (about_window.winfo_screenheight() // 2) - (height // 2)
        about_window.geometry(f'{width}x{height}+{x}+{y}')

        about_window.transient(self.root)
        about_window.grab_set()
        self.root.wait_window(about_window)

def main():
    root = tk.Tk()
    app = ImageDuplicateCheckerGUI(root) 
    root.mainloop()

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()


