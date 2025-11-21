import os, time, json, uuid, hashlib
from typing import Any, Dict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage


# ----------- Data File Configuration -----------

DATA_ROOT = os.environ.get("DATA_ROOT", "./data")
os.makedirs(os.path.join(DATA_ROOT, "user_data"), exist_ok=True)
print(f"Data Root Directory: {DATA_ROOT}")

# -------------------- utils --------------------

def now() -> int:
    return int(time.time())

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def user_dir(user_id: str) -> str:
    return os.path.join(DATA_ROOT, "user_data", user_id)

def user_meta_path(user_id: str) -> str:
    return os.path.join(user_dir(user_id), "user.meta.json")

def user_token_hash_path(user_id: str) -> str:
    return os.path.join(user_dir(user_id), "token.hash")

def user_memory_path(user_id: str) -> str:
    return os.path.join(user_dir(user_id), "memory.jsonl")

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path: str, obj: Any):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def auth_user(req) -> Optional[str]:
    """Return user_id if identity token is valid, else None."""
    token = req.headers.get("X-Identity-Token", "") or (req.json or {}).get("identity_token", "")
    if not token:
        return None
    token_h = sha256(token)
    # naive lookup: scan all user_data (OK for coursework); could keep a central index file later
    root = os.path.join(DATA_ROOT, "user_data")
    if not os.path.exists(root):
        return None
    for uid in os.listdir(root):
        tpath = user_token_hash_path(uid)
        try:
            with open(tpath, "r", encoding="utf-8") as f:
                if f.read().strip() == token_h:
                    return uid
        except Exception:
            continue
    return None

def to_lc(msg: Dict) -> BaseMessage:
    t, c = msg.get("type"), msg.get("content")
    if t == "system": return SystemMessage(content=c)
    if t == "human":  return HumanMessage(content=c)
    if t == "ai":     return AIMessage(content=c)
    if t == "tool":
        tool_call_id = None
        if isinstance(c, dict):
            tool_call_id = c.get("tool_call_id")
            c = c.get("text", "")
        return ToolMessage(content=c or "", tool_call_id=tool_call_id)
    # fallback
    return SystemMessage(content=str(c))

def from_lc(m: BaseMessage) -> Dict:
    if isinstance(m, SystemMessage): return {"type":"system", "content": m.content}
    if isinstance(m, HumanMessage):  return {"type":"human",  "content": m.content}
    if isinstance(m, AIMessage):     return {"type":"ai",     "content": m.content}
    if isinstance(m, ToolMessage):   return {"type":"tool",   "content": {"text": m.content}}
    return {"type":"system", "content": str(m)}

def session_state_path(user_id: str, session_id: str) -> str:
    return os.path.join(user_dir(user_id), "sessions", session_id, "state.jsonl")

def session_dir(user_id: str, session_id: str) -> str:
    return os.path.join(user_dir(user_id), "sessions", session_id)
