"""比对模块"""
import os
import json
import cv2,sys
import numpy as np
import torch
import torch.nn as nn
import multiprocessing
from functools import partial
from pathlib import Path

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent / relative_path

# ===================== 配置 =====================
MODEL_PATH = get_resource_path("tiny_similarity.pth")
TEMP_FOLDER = "_image_temp"
DB_PATH = os.path.join(TEMP_FOLDER, "db.json")
RESULT_JS = os.path.join(TEMP_FOLDER, "duplicates.js")
IMG_INPUT_SIZE = 128
PROCESS_NUM = max(1, multiprocessing.cpu_count())

def load_similarity_threshold():
    """从配置文件加载相似度阈值"""
    config_path = os.path.join(TEMP_FOLDER, "config.json")
    default_threshold = 0.9971
    
    
    try:
        if os.path.exists(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            threshold = config.get("similarity_threshold", default_threshold)
            return float(threshold)
        else:
            return default_threshold
    except Exception as e:
        print(f"读取配置文件失败，使用默认阈值: {str(e)}")
        return default_threshold

SIMILARITY_THRESH = load_similarity_threshold()

# ===================== 模型 =====================
class TinyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.feat = nn.Sequential(
            nn.Conv2d(3, 8, 3, 2, 1), nn.ReLU(),
            nn.Conv2d(8, 16, 3, 2, 1), nn.ReLU(),
            nn.Flatten()
        )
        self.sim = nn.Sequential(
            nn.Linear(16 * 32 * 32, 32), nn.ReLU(),
            nn.Linear(32, 1), nn.Sigmoid()
        )

    def forward(self, x1, x2):
        f1 = self.feat(x1)
        f2 = self.feat(x2)
        return self.sim(torch.abs(f1 - f2)).squeeze()

def load_model_for_device(device="cpu"):
    """加载模型到指定设备"""
    model = TinyModel()
    model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
    if device != "cpu":
        model = model.to(device)
    model.eval()
    return model

# ===================== 中文路径 =====================
def cv2_imread(file_path):
    try:
        stream = open(file_path, 'rb')
        bytes = bytearray(stream.read())
        numpyarray = np.asarray(bytes, dtype=np.uint8)
        return cv2.imdecode(numpyarray, cv2.IMREAD_UNCHANGED)
    except:
        return None

def process_image_tensor(path, device="cpu"):
    """处理图片为张量"""
    img = cv2_imread(path)
    if img is None:
        return None
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (IMG_INPUT_SIZE, IMG_INPUT_SIZE))
    img = img.astype(np.float32) / 255.0
    img = img.transpose(2, 0, 1)
    t = torch.tensor(img).unsqueeze(0)
    if device != "cpu":
        t = t.to(device)
    return t

def similarity_mp(args, threshold):
    """多进程相似度计算函数"""
    thumbA, thumbB, pathA, pathB = args
    try:
        model = TinyModel()
        model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
        model.eval()
        
        imgA = cv2_imread(thumbA)
        imgB = cv2_imread(thumbB)
        
        if imgA is None or imgB is None:
            return None
            
        def preprocess(img):
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (IMG_INPUT_SIZE, IMG_INPUT_SIZE))
            img = img.astype(np.float32) / 255.0
            img = img.transpose(2, 0, 1)
            return torch.tensor(img).unsqueeze(0)
        
        t1 = preprocess(imgA)
        t2 = preprocess(imgB)
        
        with torch.no_grad():
            sim = float(model(t1, t2).item())
        
        if sim >= threshold:
            return tuple(sorted((pathA, pathB)))
        else:
            return None
    except Exception as e:
        return None

class Comparator:
    """比对器类"""
    
    def __init__(self, db, progress_callback=None, log_callback=None,use_gpu=False, threshold=SIMILARITY_THRESH):
        self.db = db
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.use_gpu = use_gpu
        self.threshold = threshold
        self.comparing = False
        self.stop_requested = False
        
        if use_gpu:
            if torch.cuda.is_available():
                self.device = "cuda"
            elif torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
                self.use_gpu = False
        else:
            self.device = "cpu"
    
    def log(self, message):
        """记录日志"""
        if self.log_callback:
            self.log_callback(message)
    
    def update_progress(self, current, total, message=""):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(current, total, message)
    
    def compare_gpu(self, file_list, start_idx=0):
        """GPU比对"""
        self.log(f"使用GPU进行比对 (设备: {self.device})")
        
        model = load_model_for_device(self.device)
        n = len(file_list)
        total_pairs = n * (n - 1) // 2
        
        duplicates = set()
        done = start_idx
        
        tensors = []
        valid_indices = []
        
        self.log("预加载图片张量...")
        for i, path in enumerate(file_list):
            thumb_path = self.db["files"][path]["thumb"]
            tensor = process_image_tensor(thumb_path, self.device)
            if tensor is not None:
                tensors.append(tensor)
                valid_indices.append(i)
            self.update_progress(i + 1, n, f"加载张量: {i+1}/{n}")
        
        self.log(f"成功加载 {len(tensors)}/{n} 个有效张量")
        
        # 计算已经处理了多少对
        processed_pairs = 0
        for idx_i, i in enumerate(valid_indices):
            for idx_j, j in enumerate(valid_indices[idx_i + 1:]):
                if processed_pairs < start_idx:
                    processed_pairs += 1
                    continue
                    
                if self.stop_requested:
                    break
                    
                t1 = tensors[idx_i]
                t2 = tensors[idx_i + 1 + idx_j]
                done += 1
                
                try:
                    with torch.no_grad():
                        sim = float(model(t1, t2).item())
                    
                    if sim >= self.threshold:
                        duplicates.add(tuple(sorted((file_list[i], file_list[j]))))
                
                except Exception as e:
                    self.log(f"比对 {file_list[i]} <-> {file_list[j]} 时出错: {str(e)}")
                
                # 更新进度
                if done % 100 == 0 or done == total_pairs:
                    self.update_progress(done, total_pairs, f"比对: {done}/{total_pairs}")
                
                # 每1000组保存一次进度
                if done % 1000 == 0:
                    self.db["compare_index"] = done
                    with open(DB_PATH, 'w', encoding='utf-8') as f:
                        json.dump(self.db, f, ensure_ascii=False, indent=2)
        
        return duplicates
    
    def compare_cpu(self, file_list, start_idx=0):
        """CPU多进程比对"""
        self.log(f"使用多进程进行比对 (进程数: {PROCESS_NUM})")
        
        n = len(file_list)
        total_pairs = n * (n - 1) // 2
        
        tasks = []
        for i in range(n):
            for j in range(i + 1, n):
                a = file_list[i]
                b = file_list[j]
                ta = self.db["files"][a]["thumb"]
                tb = self.db["files"][b]["thumb"]
                tasks.append((ta, tb, a, b))
        
        pool = multiprocessing.Pool(PROCESS_NUM)
        func = partial(similarity_mp, threshold=self.threshold)
        
        duplicates = set()
        done = start_idx
        
        try:
            # 跳过已经处理的任务
            for idx, task in enumerate(tasks):
                if idx < start_idx:
                    continue
                    
                if self.stop_requested:
                    break
                    
                res = func(task)
                done += 1
                
                if res:
                    duplicates.add(res)
                
                # 更新进度
                if done % 100 == 0 or done == total_pairs:
                    self.update_progress(done, total_pairs, f"比对: {done}/{total_pairs}")
                
                # 每1000组保存一次进度
                if done % 1000 == 0:
                    self.db["compare_index"] = done
                    with open(DB_PATH, 'w', encoding='utf-8') as f:
                        json.dump(self.db, f, ensure_ascii=False, indent=2)
        
        except Exception as e:
            self.log(f"多进程比对出错: {str(e)}")
        finally:
            pool.close()
            pool.join()
        
        return duplicates
    
    def start_compare(self):
        """开始比对"""
        if self.comparing:
            return False
        
        self.comparing = True
        self.stop_requested = False
        
        try:
            file_list = list(self.db["files"].keys())
            if not file_list:
                self.log("没有可比的图片")
                return False
            
            n = len(file_list)
            total_pairs = n * (n - 1) // 2
            
            self.log(f"开始比对 {n} 张图片，共 {total_pairs} 对组合")
            
            # 检查断点续扫
            last_compare_count = self.db.get("last_compare_count", 0)
            compare_index = self.db.get("compare_index", 0)
            
            if len(file_list) != last_compare_count:
                self.log("检测到文件数量变化，重置比对进度...")
                self.db["compare_index"] = 0
                self.db["last_compare_count"] = len(file_list)
                with open(DB_PATH, 'w', encoding='utf-8') as f:
                    json.dump(self.db, f, ensure_ascii=False, indent=2)
                start_idx = 0
            else:
                start_idx = compare_index
                if start_idx >= total_pairs:
                    self.log("比对进度：已完成")
                    return True
                self.log(f"续比对：从第 {start_idx}/{total_pairs} 组开始")
            
            # 执行比对
            if self.use_gpu:
                duplicates = self.compare_gpu(file_list, start_idx)
            else:
                duplicates = self.compare_cpu(file_list, start_idx)
            
            # 将重复对转换为相似图片分组
            duplicate_groups = self._convert_to_groups(duplicates)
            
            self.db["duplicates"] = [list(x) for x in duplicates]
            self.db["duplicate_groups"] = duplicate_groups  
            self.db["compare_index"] = total_pairs 
            with open(DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, ensure_ascii=False, indent=2)
            
            with open(RESULT_JS, 'w', encoding='utf-8') as f:
                f.write(f"const duplicates={json.dumps(self.db['duplicates'], ensure_ascii=False)};")
                f.write(f"\nconst duplicateGroups={json.dumps(duplicate_groups, ensure_ascii=False)};")
            
            self.log(f"比对完成，发现 {len(duplicates)} 个重复对，{len(duplicate_groups)} 个相似组")
            self.log(f"结果已保存到 {RESULT_JS}")
            
            return True
            
        except Exception as e:
            self.log(f"比对过程中出错: {str(e)}")
            return False
        finally:
            self.comparing = False
    
    def _convert_to_groups(self, duplicates):
        """将重复对转换为相似图片分组"""
        graph = {}
        for a, b in duplicates:
            if a not in graph:
                graph[a] = set()
            if b not in graph:
                graph[b] = set()
            graph[a].add(b)
            graph[b].add(a)
        
        # 使用深度优先搜索找到连通分量
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
        
        return groups
    
    def stop_compare(self):
        """停止比对"""
        self.stop_requested = True
        self.comparing = False