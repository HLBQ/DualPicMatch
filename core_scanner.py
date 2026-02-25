"""扫描模块"""
import os
import json
import cv2
import numpy as np
from pathlib import Path
import threading
from queue import Queue

# ===================== 配置 =====================
TEMP_FOLDER = "_image_temp"
DB_PATH = os.path.join(TEMP_FOLDER, "db.json")
IMG_MAX_SIZE = 400
THREAD_NUM = 8

# 支持的图片格式
DEFAULT_ALLOW_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif", ".gif"}

def get_allowed_extensions():
    """从配置获取配置"""
    config_path = os.path.join(TEMP_FOLDER, "config.json")
    
    try:
        if os.path.exists(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            allowed_exts = config.get("allowed_extensions", list(DEFAULT_ALLOW_EXTS))

            if isinstance(allowed_exts, list):
                return set(allowed_exts)
            elif isinstance(allowed_exts, set):
                return allowed_exts
            else:
                return DEFAULT_ALLOW_EXTS
        else:
            return DEFAULT_ALLOW_EXTS
    except Exception as e:
        print(f"读取配置文件失败，使用默认格式: {str(e)}")
        return DEFAULT_ALLOW_EXTS

ALLOW_EXTS = get_allowed_extensions()

def cv2_imread(file_path):
    try:
        stream = open(file_path, 'rb')
        bytes = bytearray(stream.read())
        numpyarray = np.asarray(bytes, dtype=np.uint8)
        return cv2.imdecode(numpyarray, cv2.IMREAD_UNCHANGED)
    except:
        return None

def cv2_imwrite(file_path, img):
    try:
        ext = '.png'
        success, enc = cv2.imencode(ext, img)
        if success:
            with open(file_path, 'wb') as f:
                enc.tofile(f)
        return success
    except:
        return False

def copy_and_process_image(src, dst):
    """复制并处理图片到临时文件夹"""
    img = cv2_imread(src)
    if img is None:
        return False
    
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    
    h, w = img.shape[:2]
    
    if max(h, w) <= 400:
        if h >= w:
            scale = 400.0 / h
        else:
            scale = 400.0 / w
    else:
        scale = 400.0 / max(h, w)
    
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    if new_w < 400 and new_h < 400:
        if new_h >= new_w:
            scale = 400.0 / new_h
            new_w = int(new_w * scale)
            new_h = 400
        else:
            scale = 400.0 / new_w
            new_w = 400
            new_h = int(new_h * scale)
    
    # 调整图片大小
    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    
    return cv2_imwrite(dst, img)

def resize_and_save(src, dst):
    """调整图片大小并保存为缩略图"""
    return copy_and_process_image(src, dst)

def load_db():
    """加载数据库"""
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    if not os.path.exists(DB_PATH):
        db = {
            "state": "idle", "index": 0, "files": {}, "duplicates": [],
            "scan_processed": 0, "last_file_list": [], "last_file_count": 0
        }
        save_db(db)
        return db
    with open(DB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_db(db):
    """保存数据库"""
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def scan_images():
    """扫描所有图片文件"""
    res = []
    temp_abs = Path(TEMP_FOLDER).resolve()
    for p in Path('.').rglob('*'):
        try:
            if temp_abs in p.resolve().parents:
                continue
        except:
            continue
        if p.suffix.lower() in ALLOW_EXTS:
            try:
                res.append(str(p.resolve()).replace('\\', '/').strip())
            except:
                continue
    return sorted(list(set(res)))

class Scanner:
    """扫描器类"""
    
    def __init__(self, db, progress_callback=None, log_callback=None):
        self.db = db
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.scanning = False
        self.stop_requested = False
        
    def log(self, message):
        """记录日志"""
        if self.log_callback:
            self.log_callback(message)
    
    def update_progress(self, current, total, message=""):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(current, total, message)
    
    def worker(self, q, lock, total):
        """工作线程"""
        while not self.stop_requested:
            try:
                item = q.get(timeout=1)
                if item is None:
                    break
                    
                path, idx = item
                try:
                    with lock:
                        file_count = len(self.db["files"])
                        tid = f"img_{file_count}"
                        thumb = os.path.join(TEMP_FOLDER, f"{tid}.png").replace('\\', '/')
                        
                        self.db["files"][path] = {"id": tid, "thumb": thumb}
                        self.db["scan_processed"] += 1
                    
                    # 处理图片
                    success = resize_and_save(path, thumb)
                    
                    if not success:
                        # 数据库中移除
                        with lock:
                            if path in self.db["files"]:
                                del self.db["files"][path]
                                self.db["scan_processed"] -= 1
                    
                    # 保存数据库
                    if self.db["scan_processed"] % 10 == 0:
                        with lock:
                            save_db(self.db)
                    
                    processed = self.db["scan_processed"]
                    self.update_progress(processed, total, f"处理: {processed}/{total}")
                    
                except Exception as e:
                    self.log(f"处理文件 {path} 时出错: {str(e)}")
                finally:
                    q.task_done()
                    
            except:
                if self.stop_requested:
                    break
                continue
    
    def start_scan(self):
        """开始扫描"""
        if self.scanning:
            return False
        
        self.scanning = True
        self.stop_requested = False
        
        try:
            all_files = scan_images()
            total = len(all_files)
            self.log(f"扫描到 {total} 张图片")
            
            cur_files = sorted(all_files)
            cur_cnt = len(cur_files)
            last_cnt = self.db.get("last_file_count", 0)
            last_files = self.db.get("last_file_list", [])
            scan_processed = self.db.get("scan_processed", 0)
            
            finished = (scan_processed == last_cnt) and last_cnt > 0
            
            if last_cnt == 0 or cur_cnt != last_cnt:
                self.log(f"首次扫描或文件数量变化: 上次 {last_cnt} 个文件，本次 {cur_cnt} 个文件")
                
                # 新增文件
                new_files = [f for f in cur_files if f not in last_files]
                
                # 删除文件
                deleted_files = [f for f in last_files if f not in cur_files]
                
                if deleted_files:
                    self.log(f"发现 {len(deleted_files)} 个被删除的文件")
                    # 从数据库中移除被删除的文件
                    for f in deleted_files:
                        if f in self.db["files"]:
                            del self.db["files"][f]
                    
                    # 重新序列化ID
                    self._resequence_file_ids()
                
                if new_files:
                    self.log(f"发现 {len(new_files)} 个新增文件")
                    todo = new_files
                    prog = scan_processed
                else:
                    self.log("发现有文件被删除")
                    self.db["last_file_list"] = cur_files
                    self.db["last_file_count"] = cur_cnt
                    save_db(self.db)
                    return True
            else:
                if finished:
                    if cur_files == last_files:
                        self.log("文件无变化")
                        return True
                    else:
                        self.log("文件列表发生改动，重新扫描")
                        self.db["files"] = {}
                        self.db["scan_processed"] = 0
                        self.db["last_file_count"] = cur_cnt
                        self.db["last_file_list"] = cur_files
                        save_db(self.db)
                        prog = 0
                        todo = cur_files
                else:
                    prog = scan_processed
                    todo = cur_files[prog:]
                    self.log(f"续扫 {prog}/{cur_cnt}")
            
            if not todo:
                self.log("没有需要处理的文件")
                return True
            
            q = Queue()
            lock = threading.Lock()
            
            for i, p in enumerate(todo):
                q.put((p, prog + i))
            
            workers = []
            for _ in range(min(THREAD_NUM, len(todo))):
                t = threading.Thread(target=self.worker, args=(q, lock, total), daemon=True)
                t.start()
                workers.append(t)
            
            q.join()
            
            for _ in range(len(workers)):
                q.put(None)
            
            for t in workers:
                t.join(timeout=1)
            
            self.db["last_file_list"] = cur_files
            self.db["last_file_count"] = cur_cnt
            save_db(self.db)
            
            self.log("扫描完成")
            return True
            
        except Exception as e:
            self.log(f"扫描过程中出错: {str(e)}")
            return False
        finally:
            self.scanning = False
    
    def _resequence_file_ids(self):
        """重新序列化文件ID"""
        files = self.db["files"]
        sorted_files = sorted(files.items(), key=lambda x: x[0])  
        
        # 重新分配ID
        for idx, (file_path, file_info) in enumerate(sorted_files):
            new_id = f"img_{idx}"
            new_thumb = os.path.join(TEMP_FOLDER, f"{new_id}.png").replace('\\', '/')
            
            old_thumb = file_info.get("thumb", "")
            if old_thumb and os.path.exists(old_thumb):
                try:
                    os.rename(old_thumb, new_thumb)
                except:
                    try:
                        import shutil
                        shutil.copy2(old_thumb, new_thumb)
                    except:
                        pass
            
            files[file_path] = {"id": new_id, "thumb": new_thumb}
        
        self.log(f"已重新序列化 {len(files)} 个文件的ID")
    
    def stop_scan(self):
        """停止扫描"""
        self.stop_requested = True
        self.scanning = False