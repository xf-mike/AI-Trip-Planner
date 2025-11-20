# app.py
# Minimal multi-user & multi-session backend + Static frontend hosting
# Endpoints:
#   POST /api/create_user                -> { user_id, identity_token }
#   POST /api/create_session             -> { session_id }
#   GET  /api/get_sessions               -> [ {session_id, session_name, created_at}, ...] (newest first)
#   GET  /api/get_conversation_history   -> { messages: [...] }
#   POST /api/chat                       -> { last_ai: {type:"ai", content:"..."} }  (optionally stream=1 to SSE)
#
# Storage layout (under ./data):
#   ./data/user_data/<user_id>/user.meta.json
#   ./data/user_data/<user_id>/memory.jsonl    # long-term memory if use SimpleMemory
#   ./data/user_data/<user_id>/sessions/<session_id>/state.jsonl
#   [LTM (long-term memory) can be also run above Weaviate DB]
#
# Notes:
# - Identity: client keeps identity_token; server stores only its sha256.
# - Very light error handling; no DB/locks; single-process friendly.
# - USE_LTM=1 enables memory injection & writeback; otherwise off.
# - If context.trim_context exists, we call it; else we pass messages as-is.

from __future__ import annotations
import os, json, time, uuid, hashlib, logging
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS

# your project modules
from trip_planner.orchestrate import make_app
from trip_planner.tools import TOOLS
from trip_planner.llm import init_llm
from trip_planner.role import role_template
from trip_planner.memory import SimpleMemory, format_mem_snippets
from trip_planner.vectorDB import WeaviateMemory
try:
    from trip_planner.context import trim_context as _trim_context
except Exception:
    _trim_context = None

# langchain message types
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage

# -------------------- config --------------------
DATA_ROOT = os.environ.get("DATA_ROOT", "./data")
USE_LTM = os.environ.get("USE_LTM", "1").lower() in {"1", "true", "yes"}
USE_VEC_DB = USE_LTM and os.environ.get("USE_VEC_DB", "1").lower() in {"1", "true", "yes"}
VERBOSE = os.environ.get("VERBOSE", "1").lower() in {"1", "true", "yes"}
MAX_TURNS = int(os.environ.get("MAX_TURNS_IN_CONTEXT", "16"))
KEEP_SYSTEM = int(os.environ.get("KEEP_SYSTEM", "2"))
RUN_AS_DEV = os.environ.get("RUN_AS_DEV", "1").lower() in {"1", "true", "yes"}

if RUN_AS_DEV:
    app = Flask(__name__)
    CORS(app)

else:
    # Vite build 输出目录
    STATIC_DIR = os.path.join(os.path.dirname(__file__), "dist")

    # 让 Flask 直接把 dist 当静态根目录
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/")

    # 关闭 werkzeug 自带的访问日志
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)  # 只输出错误日志（不打印普通请求）


if USE_VEC_DB:
    # initialize WeaviateMemory
    memory_store = None
    try:
        # Initialize the client once, globally
        memory_store = WeaviateMemory(openai_key=os.environ.get("OPENAI_API_KEY"))

    except Exception as e:
        print(f"WARNING: Failed to initialize WeaviateMemory client: {e}")
        print(f"\nUse SimpleMemory instead.")
        USE_VEC_DB = False # Disable if connection fails


# model & orchestrator (stateless)
_llm = init_llm(TOOLS)
_invoke = make_app(_llm, TOOLS)
print(f"Memory: Short{'+Long' if USE_LTM else ''} | Max context scale: {MAX_TURNS}")
print(f"Running Mode: {'Development' if RUN_AS_DEV else 'Production'}")

# -------------------- Frontend Hosting --------------------
# 前端路由兜底：不是 /api 的都交给 index.html
if not RUN_AS_DEV:
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def catch_all(path):
        # /api/* 由后端处理；其余路径返回前端入口
        if path.startswith("api/"):
            return ("Not Found", 404)
        return send_from_directory(app.static_folder, "index.html")

# -------------------- utils --------------------
def _now() -> float:
    return time.time()

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _user_dir(user_id: str) -> str:
    return os.path.join(DATA_ROOT, "user_data", user_id)

def _user_meta_path(user_id: str) -> str:
    return os.path.join(_user_dir(user_id), "user.meta.json")

def _user_token_hash_path(user_id: str) -> str:
    return os.path.join(_user_dir(user_id), "token.hash")

def _user_memory_path(user_id: str) -> str:
    return os.path.join(_user_dir(user_id), "memory.jsonl")

def _session_dir(user_id: str, session_id: str) -> str:
    return os.path.join(_user_dir(user_id), "sessions", session_id)

def _session_state_path(user_id: str, session_id: str) -> str:
    return os.path.join(_session_dir(user_id, session_id), "state.jsonl")

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: str, obj: Any):
    _ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _append_jsonl(path: str, obj: Any):
    _ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _read_jsonl(path: str) -> List[Dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:
        pass
    return out

def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def _auth_user(req) -> Optional[str]:
    """Return user_id if identity token is valid, else None."""
    token = req.headers.get("X-Identity-Token", "") or (req.json or {}).get("identity_token", "")
    if not token:
        return None
    token_h = _sha256(token)
    # naive lookup: scan all user_data (OK for coursework); could keep a central index file later
    root = os.path.join(DATA_ROOT, "user_data")
    if not os.path.exists(root):
        return None
    for uid in os.listdir(root):
        tpath = _user_token_hash_path(uid)
        try:
            with open(tpath, "r", encoding="utf-8") as f:
                if f.read().strip() == token_h:
                    return uid
        except Exception:
            continue
    return None

def _to_lc(msg: Dict) -> BaseMessage:
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

def _from_lc(m: BaseMessage) -> Dict:
    if isinstance(m, SystemMessage): return {"type":"system", "content": m.content}
    if isinstance(m, HumanMessage):  return {"type":"human",  "content": m.content}
    if isinstance(m, AIMessage):     return {"type":"ai",     "content": m.content}
    if isinstance(m, ToolMessage):   return {"type":"tool",   "content": {"text": m.content}}
    return {"type":"system", "content": str(m)}

def _trim(msgs: List[BaseMessage]) -> List[BaseMessage]:
    if _trim_context:
        # 使用安全裁剪（块级/必保最近 human）
        try:
            return _trim_context(msgs, MAX_TURNS, keep_system=KEEP_SYSTEM)
        except Exception:
            pass
    # 兜底：只保留开头一个 system + 最近若干条
    out = []
    if msgs and isinstance(msgs[0], SystemMessage):
        out.append(msgs[0])
        rest = msgs[1:][- (MAX_TURNS - 1):]
        out.extend(rest)
        return out
    return msgs[-MAX_TURNS:]

# -------------------- User Metadata --------------------
USER_NAME_MAP = {}

# 用户名加载函数
def _load_user_names():
    global USER_NAME_MAP
    root = os.path.join(DATA_ROOT, "user_data")
    if not os.path.exists(root):
        return
    for uid in os.listdir(root):
        meta_path = _user_meta_path(uid)
        # 优化：只读一次文件
        meta = _read_json(meta_path, {})
        if meta and "name" in meta:
            USER_NAME_MAP[uid] = meta["name"]
    print(f"[INFO] Loaded metadata for {len(USER_NAME_MAP)} users.")

# 记忆片段 ID 到 Name 的映射辅助函数
def _map_snippets_to_names(snips: List[Tuple[Any, float]]) -> List[Tuple[Any, float]]:
    """Replaces user_id with username in the MemoryItem object's user_id field for formatting."""
    for item, score in snips:
        original_uid = getattr(item, 'user_id', None)
        
        if original_uid:
            # 查找用户名，如果不存在则使用原来的 user_id 作为 fallback
            username = USER_NAME_MAP.get(original_uid, original_uid)
            # 替换 MemoryItem 对象实例的 user_id 属性
            setattr(item, 'user_id', username) 
            
    return snips

# Init user data
_load_user_names()

# -------------------- Global Relationships Management --------------------
RELATIONSHIPS_FILE = os.path.join(DATA_ROOT, "relationships.json")
RELATIONSHIPS = {} 

def _load_relationships():
    global RELATIONSHIPS
    if os.path.exists(RELATIONSHIPS_FILE):
        RELATIONSHIPS = _read_json(RELATIONSHIPS_FILE, {})
    else:
        RELATIONSHIPS = {}
    print(f"[INFO] Loaded relationships for {len(RELATIONSHIPS)} users.")

def _save_relationships():
    _write_json(RELATIONSHIPS_FILE, RELATIONSHIPS)

def _ensure_user_rel(uid):
    """Helper ensuring a user dict exists in global RELATIONSHIPS."""
    if uid not in RELATIONSHIPS:
        RELATIONSHIPS[uid] = {"amplify_from": [], "exposed_to": []}

# Init relationshps
_load_relationships()

# -------------------- endpoints --------------------

@app.get("/api/healthz")
def healthz():
    return {"ok": True, "use_ltm": USE_LTM, "use_vec_db": USE_VEC_DB}


@app.post("/api/create_user")
def create_user():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400

    user_id = _gen_id("u")
    identity_token = uuid.uuid4().hex + uuid.uuid4().hex  # long random
    token_h = _sha256(identity_token)

    #  初始化用户的memory sharing网络
    _ensure_user_rel(user_id)
    _save_relationships()

    # update metadata
    USER_NAME_MAP[user_id] = name

    # create dirs and files
    udir = _user_dir(user_id)
    _ensure_dir(os.path.join(udir, "sessions"))
    _write_json(_user_meta_path(user_id), {
        "user_id": user_id,
        "name": name,
        "description": description,
        "created_at": _now()
    })
    with open(_user_token_hash_path(user_id), "w", encoding="utf-8") as f:
        f.write(token_h)

    if USE_LTM:

        if USE_VEC_DB:  # init memory with name/description using Weaviate
            try:
                if name:
                    memory_store.remember(user_id, f"User name: {name}", kind="profile", meta={}, verbose=VERBOSE)
                if description:
                    memory_store.remember(user_id, f"User description: {description}", kind="profile", meta={}, verbose=VERBOSE)
            except Exception as e:
                print(f"Error remembering profile for user {user_id}: {e}")

        else:  # use SimpleMemory
            try:
                mem = SimpleMemory(path=_user_memory_path(user_id))
                if name:
                    mem.remember(f"User name: {name}", kind="profile", meta={})
                if description:
                    mem.remember(f"User description: {description}", kind="profile", meta={})
            except Exception:
                print(f"Error remembering profile for user {user_id}: {e}")
                _ensure_dir(udir)
                open(_user_memory_path(user_id), "a", encoding="utf-8").close()

    return jsonify({"user_id": user_id, "identity_token": identity_token})

@app.post("/api/create_session")
def create_session():
    user_id = _auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(force=True)
    session_name = (data.get("session_name") or "").strip() or f"session-{int(_now())}"
    session_id = _gen_id("s")
    sdir = _session_dir(user_id, session_id)
    _ensure_dir(sdir)
    # init state with a system message (role)
    _append_jsonl(_session_state_path(user_id, session_id), {"type":"system", "content": role_template, "ts": _now()})
    # write simple index
    _write_json(os.path.join(sdir, "index.json"), {
        "session_id": session_id,
        "session_name": session_name,
        "created_at": _now()
    })
    return jsonify({"session_id": session_id})

@app.get("/api/get_sessions")
def get_sessions():
    user_id = _auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401

    # read user info
    username = USER_NAME_MAP.get(user_id, "User")

    # concatenate
    sroot = os.path.join(_user_dir(user_id), "sessions")
    sessions = []
    if os.path.exists(sroot):
        for sid in os.listdir(sroot):
            idxp = os.path.join(sroot, sid, "index.json")
            meta = _read_json(idxp, {})
            if meta:
                sessions.append(meta)
    sessions.sort(key=lambda x: x.get("created_at", 0), reverse=True)

    return jsonify({"username": username, "sessions": sessions})


@app.get("/api/get_conversation_history")
def get_conversation_history():
    user_id = _auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401
    session_id = request.args.get("session_id", "")
    if not session_id:
        return jsonify({"error":"session_id required"}), 400

    statep = _session_state_path(user_id, session_id)
    rows = _read_jsonl(statep)[1:]  # Do not send the system prompt to user
    messages = [ {"type": r.get("type"), "content": r.get("content")} for r in rows ]
    return jsonify({"messages": messages})


#  获取关系接口
@app.get("/api/get_relationships")
def get_relationships():
    user_id = _auth_user(request)
    if not user_id: return jsonify({"error":"unauthorized"}), 401
    
    _ensure_user_rel(user_id)
    # 重新加载以防其他进程修改(虽然单进程不用，但为了稳健)
    # _load_relationships() 
    return jsonify(RELATIONSHIPS[user_id])


#  严格保持数据一致性的更新接口
@app.post("/api/update_relationships")
def update_relationships():
    """
    更新当前用户的关系网。
    逻辑：维护 'Arrow' (A -> B) 的一致性。
    - A.exposed_to 包含 B <==> B.amplify_from 包含 A
    用户可以单方面切断箭头。
    """
    user_id = _auth_user(request)
    if not user_id: return jsonify({"error":"unauthorized"}), 401
    
    _ensure_user_rel(user_id)
    data = request.get_json(force=True)
    
    # 1. 处理 'exposed_to' 变更 (我控制谁能看我)
    # -------------------------------------------------
    if "exposed_to" in data:
        new_exposed = set(data["exposed_to"])
        old_exposed = set(RELATIONSHIPS[user_id]["exposed_to"])
        
        # 计算差集
        to_add = new_exposed - old_exposed     # 新增的箭头 A->B
        to_remove = old_exposed - new_exposed  # 删除的箭头 A->B
        
        # 执行本地更新
        RELATIONSHIPS[user_id]["exposed_to"] = list(new_exposed)
        
        # [联动更新]: 既然我暴露给 B (A->B)，那么 B 的 amplify_from 必须包含 A
        for target_id in to_add:
            _ensure_user_rel(target_id)
            if user_id not in RELATIONSHIPS[target_id]["amplify_from"]:
                RELATIONSHIPS[target_id]["amplify_from"].append(user_id)
        
        # [联动更新]: 既然我不给 B 看了，那么 B 的 amplify_from 必须移除 A
        for target_id in to_remove:
            _ensure_user_rel(target_id)
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
        
        # 用户只能"取关"(删除箭头)，不能未经允许"关注"(新增箭头)
        # 如果前端传了新增的 ID，而那个 ID 并没有 expose 给当前用户，这通常是非法操作。
        # 但为了健壮性，我们只处理"删除"操作的一致性，或者完全信任 exposed_to 逻辑。
        
        # 这里我们实现双向一致性：如果我不再 amplify B，意味着箭头 A<-B 断裂，
        # 那么 B 的 exposed_to 也应该移除 A。
        RELATIONSHIPS[user_id]["amplify_from"] = list(new_amplify)
        
        for src_id in to_remove_src:
            _ensure_user_rel(src_id)
            if user_id in RELATIONSHIPS[src_id]["exposed_to"]:
                RELATIONSHIPS[src_id]["exposed_to"].remove(user_id)

    _save_relationships()
    return jsonify({"status": "ok", "current": RELATIONSHIPS[user_id]})


@app.post("/api/chat")
def chat():
    """Non-streaming chat: append user msg -> build context -> call graph -> append ai -> return last_ai.
       If you want streaming SSE, pass ?stream=1 (we simulate SSE by sending the final text once)."""
    user_id = _auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401

    stream = request.args.get("stream", "0") in {"1", "true", "yes"}
    data = request.get_json(force=True)
    session_id = data.get("session_id", "")
    message = data.get("message", {})
    should_share = len(RELATIONSHIPS[user_id]["exposed_to"]) > 0
    external_source_ids = RELATIONSHIPS[user_id]["amplify_from"]

    if not session_id or not message:
        return jsonify({"error":"session_id and message required"}), 400

    # 1) append the human message to state.jsonl
    statep = _session_state_path(user_id, session_id)
    _append_jsonl(statep, {"type": message.get("type","human"), "content": message.get("content",""), "ts": _now()})

    # 2) read state messages
    raw_msgs = _read_jsonl(statep)
    msgs_lc: List[BaseMessage] = []
    for r in raw_msgs:
        msgs_lc.append(_to_lc({"type": r.get("type"), "content": r.get("content")}))

    # 3) optional memory injection (one-off SystemMessage)
    if USE_LTM:
        last_human = None
        for m in reversed(msgs_lc):
            if isinstance(m, HumanMessage):
                last_human = m.content; break
        if last_human:
            try:
                if USE_VEC_DB:
                    snips = memory_store.retrieve(
                        user_id, 
                        last_human, 
                        k=4, 
                        min_sim=0.55, 
                        verbose=VERBOSE,
                        external_user_ids=external_source_ids 
                    )
                    snips = _map_snippets_to_names(snips)  
                else:
                    snips = SimpleMemory(path=_user_memory_path(user_id)).retrieve(last_human, k=4, min_sim=0.55, verbose=VERBOSE)

                if snips:
                    mem_text = format_mem_snippets(snips, current_user_id=USER_NAME_MAP.get(user_id, user_id), verbose=VERBOSE)
                    insert_at = 1 if msgs_lc and isinstance(msgs_lc[0], SystemMessage) else 0
                    msgs_lc = msgs_lc[:insert_at] + [SystemMessage(content=mem_text)] + msgs_lc[insert_at:]
            except Exception as e:
                print(f"Error retrieving memory for user {user_id}: {e}")

    # 4) trim context (safe) then call orchestrator
    msgs_trimmed = _trim(msgs_lc)
    state_after = _invoke({"messages": msgs_trimmed})
    last_ai = next((m for m in reversed(state_after["messages"]) if isinstance(m, AIMessage)), None)
    ai_text = last_ai.content if last_ai else "[No response]"

    # 5) append AI to persistent state
    _append_jsonl(statep, {"type": "ai", "content": ai_text, "ts": _now()})

    # 6) optional: write to long term memory
    if USE_LTM:
        try:
            last_user = message.get("content","")
            snippet = (f"Q: {last_user}\nA: {ai_text}")[:800]
            if USE_VEC_DB:
                memory_store.remember(
                    user_id, 
                    snippet, 
                    kind="turn", 
                    meta={"session_id": session_id},
                    share=should_share,
                    verbose=VERBOSE
                )
            else:
                SimpleMemory(path=_user_memory_path(user_id)).remember(snippet, kind="turn", meta={"session_id": session_id})
        except Exception as e:
            print(f"Error remembering turn for user {user_id}: {e}")
            pass

    if not stream:
        return jsonify({"last_ai": {"type":"ai", "content": ai_text}})

    # SSE (very simple): send final text once
    def gen():
        payload = json.dumps({"delta": ai_text}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
        yield "event: done\ndata: {}\n\n"
    return Response(gen(), mimetype="text/event-stream")


if __name__ == "__main__":
    os.makedirs(DATA_ROOT, exist_ok=True)
    port = int(os.environ.get("PORT", "8080"))
    try:
        app.run(host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("\nCleaning up...")
    finally:
        if memory_store:
            memory_store.client.close()
