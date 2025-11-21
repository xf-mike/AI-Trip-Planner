import os
from typing import Dict, List
from .utils import DATA_ROOT, read_json, write_json
from .user import USER_NAME_MAP

# -------------------- Global Relationships Management --------------------
RELATIONSHIPS = {} 
_relationships_file = os.path.join(DATA_ROOT, "relationships.json")

def load_relationships():
    global RELATIONSHIPS
    if os.path.exists(_relationships_file):
        RELATIONSHIPS = read_json(_relationships_file, {})
    else:
        RELATIONSHIPS = {}
    print(f"[INFO] Loaded relationships for {len(RELATIONSHIPS)} users.")

# 初始加载关系数据
load_relationships()

def save_relationships():
    write_json(_relationships_file, RELATIONSHIPS)

def ensure_user_rel(uid):
    """Helper ensuring a user dict exists in global RELATIONSHIPS."""
    if uid not in RELATIONSHIPS:
        RELATIONSHIPS[uid] = {"amplify_from": [], "exposed_to": []}

def enrich_user_list(user_ids: List[str]) -> List[Dict[str, str]]:
    enriched = []
    for uid in user_ids:
        # 从全局 USER_NAME_MAP 获取名字，如果找不到就显示 ID
        name = USER_NAME_MAP.get(uid, f"Unknown({uid})")
        enriched.append({"id": uid, "name": name})
    return enriched

def update_relationships_for_user(user_id: str, data: Dict):
    # 1. 处理 'exposed_to' 变更 (我控制谁能看我)
    if "exposed_to" in data:
        new_exposed = set(data["exposed_to"]) # 这里的 data 依然是 ID list
        old_exposed = set(RELATIONSHIPS[user_id]["exposed_to"])
        
        # 计算差集
        to_add = new_exposed - old_exposed     # 新增的箭头 A->B
        to_remove = old_exposed - new_exposed  # 删除的箭头 A->B
        
        if (to_add - RELATIONSHIPS.keys()):
            raise ValueError("try to add invalid user IDs into exposed_to")
        
        # 执行本地更新
        RELATIONSHIPS[user_id]["exposed_to"] = list(new_exposed)
        
        # [联动更新]: 既然我暴露给 B (A->B)，那么 B 的 amplify_from 必须包含 A
        for target_id in to_add:
            if target_id in RELATIONSHIPS.keys():
                # _ensure_user_rel(target_id)
                if user_id not in RELATIONSHIPS[target_id]["amplify_from"]:
                    RELATIONSHIPS[target_id]["amplify_from"].append(user_id)
        
        # [联动更新]: 既然我不给 B 看了，那么 B 的 amplify_from 必须移除 A
        for target_id in to_remove:
            ensure_user_rel(target_id)
            if user_id in RELATIONSHIPS[target_id]["amplify_from"]:
                RELATIONSHIPS[target_id]["amplify_from"].remove(user_id)

    # 2. 处理 'amplify_from' 变更 (我控制我想看谁)
    # -------------------------------------------------
    # 注意：通常用户不能强行 amplify 别人（除非对方 expose），
    # 但如果 UI 允许用户"取关" (停止接收某人的记忆)，这里需要处理移除逻辑。
    # 为了简单，我们假设 UI 传来的数据是用户期望的最终状态。
    if "amplify_from" in data:
        new_amplify = set(data["amplify_from"])
        old_amplify = set(RELATIONSHIPS[user_id]["amplify_from"])
        
        to_remove_src = old_amplify - new_amplify
        if (new_amplify - RELATIONSHIPS.keys()) or (old_amplify - RELATIONSHIPS.keys()):
            raise ValueError("invalid user IDs specified in amplify_from")
        
        # 用户只能"取关"(删除箭头)，不能未经允许"关注"(新增箭头)
        # 如果前端传了新增的 ID，而那个 ID 并没有 expose 给当前用户，这通常是非法操作。
        # 但为了健壮性，我们只处理"删除"操作的一致性，或者完全信任 exposed_to 逻辑。
        
        # 这里我们实现双向一致性：如果我不再 amplify B，意味着箭头 A<-B 断裂，
        # 那么 B 的 exposed_to 也应该移除 A。
        RELATIONSHIPS[user_id]["amplify_from"] = list(new_amplify)
        
        for src_id in to_remove_src:
            if src_id in RELATIONSHIPS.keys():
                # _ensure_user_rel(src_id)
                if user_id in RELATIONSHIPS[src_id]["exposed_to"]:
                    RELATIONSHIPS[src_id]["exposed_to"].remove(user_id)
