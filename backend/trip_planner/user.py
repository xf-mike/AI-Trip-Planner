import os
from typing import Any, List, Tuple
from .utils import DATA_ROOT, user_meta_path, read_json


class UserModel:

    def __init__(self, mode="cli"):
        if mode == "cli":
            self = CLI()
        elif mode == "remote":
            raise ValueError("remote server unimplement!")

    def get_input(self) -> str:
        pass


    def send_update(self, message: str) -> None:
        pass
    

class CLI:
    
    def get_input(self) -> str:
        return input("[User] > ").strip().encode("utf-8", errors="replace").decode("utf-8")


    def send_response(self, message: str) -> None:
        print(f"[Agent] > {message.encode('utf-8', errors='replace').decode('utf-8')}")

# -------------------- User Metadata --------------------

USER_NAME_MAP = {}

# 用户名加载函数
def load_user_names():
    global USER_NAME_MAP
    for uid in os.listdir(DATA_ROOT + "/user_data"):
        meta_path = user_meta_path(uid)
        # 优化：只读一次文件
        meta = read_json(meta_path, {})
        if meta and "name" in meta:
            USER_NAME_MAP[uid] = meta["name"]
    print(f"[INFO] Loaded metadata for {len(USER_NAME_MAP)} users.")

# 初始加载用户名字数据
load_user_names()

# 记忆片段 ID 到 Name 的映射辅助函数
def map_snippets_to_names(snips: List[Tuple[Any, float]]) -> List[Tuple[Any, float]]:
    """Set user_name as username in the MemoryItem object's user_id field for formatting."""
    for item, _ in snips:
        original_uid = getattr(item, 'user_id', None)
        
        if original_uid:
            # 查找用户名，如果不存在则使用原来的 user_id 作为 fallback
            username = USER_NAME_MAP.get(original_uid, original_uid)
            # 设置 MemoryItem 对象实例的 user_name 属性
            setattr(item, 'user_name', username) 
            
    return snips