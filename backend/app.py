# app.py
# =============================================================================
# Multi-User AI Chat Backend & Static Frontend Host
# =============================================================================
#
# Overview:
#   A Flask-based backend supporting multiple users, persistent sessions, and 
#   Long-Term Memory (LTM). It can run in 'Development' mode (CORS enabled) 
#   or 'Production' mode (serves built static files).
#
# Configuration (Environment Variables):
#   - RUN_AS_DEV: "1" to enable CORS and disable static hosting; "0" for Prod.
#   - USE_LTM: "1" to enable Long-Term Memory injection & writeback.
#   - USE_VEC_DB: "1" to use Weaviate (requires OPENAI_API_KEY); "0" for SimpleMemory (JSONL).
#   - MAX_TURNS_IN_CONTEXT: Max interaction turns to keep in LLM context window (default: 16).
#   - OPENAI_API_KEY: Required if using Weaviate or OpenAI-based LLMs.
#
# API Endpoints:
#   [System]
#     GET  /api/healthz               -> { ok, use_ltm, cached_sessions_count }
#
#   [User & Session Management]
#     POST /api/create_user           -> { user_id, identity_token }
#     POST /api/create_session        -> { session_id }
#     GET  /api/get_sessions          -> { sessions: [{id, name, created_at}, ...] }
#     GET  /api/get_conversation_history?session_id=... -> { messages: [...] }
#
#   [Memory & Relationships]
#     GET  /api/get_relationships     -> { exposed_to: [...], amplify_from: [...] }
#     POST /api/update_relationships  -> Updates memory sharing permissions.
#
#   [Chat]
#     POST /api/chat                  -> { last_ai: { content: "..." } }
#       Payload: { session_id, message: { content } }
#       Query Param: ?stream=1 for Server-Sent Events (SSE).
#
# Storage Layout (./data):
#   ./data/user_data/<uid>/user.meta.json       # User profile
#   ./data/user_data/<uid>/memory.jsonl         # LTM (if using SimpleMemory)
#   ./data/user_data/<uid>/sessions/<sid>/      # Session state & index
#   ./data/relationships.json                   # Global user relationship graph
#
# Key Mechanics:
#   - Auth: Client holds `identity_token`; Server verifies hash (sha256).
#   - Memory: Automatic RAG injection based on vector similarity before generation.
#   - Context: Automatically trimmed via `trim_context` to fit token limits.
# =============================================================================

from __future__ import annotations
import os, json, uuid, logging
from typing import List

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

from trip_planner.utils import now, gen_id, sha256, \
    user_token_hash_path, user_dir, user_meta_path, user_memory_path, \
    session_dir, session_state_path, read_json, ensure_dir, write_json, \
    auth_user, to_lc
from trip_planner.orchestrate import make_app
from trip_planner.tools import TOOLS
from trip_planner.llm import init_llm
from trip_planner.role import role_template
from trip_planner.memory import SimpleMemory, format_mem_snippets
from trip_planner.vectorDB import WeaviateMemory
from trip_planner.cache import CACHED_SESSIONS, append_session, read_session
from trip_planner.user import USER_NAME_MAP, map_snippets_to_names
from trip_planner.relation import RELATIONSHIPS, save_relationships, \
    ensure_user_rel, enrich_user_list, update_relationships_for_user
from trip_planner.context import trim_context

# -------------------- config --------------------
USE_LTM = os.environ.get("USE_LTM", "1").lower() in {"1", "true", "yes"}
USE_VEC_DB = USE_LTM and os.environ.get("USE_VEC_DB", "1").lower() in {"1", "true", "yes"}
VERBOSE = os.environ.get("VERBOSE", "1").lower() in {"1", "true", "yes"}
MAX_TURNS = int(os.environ.get("MAX_TURNS_IN_CONTEXT", "16"))
KEEP_SYSTEM = int(os.environ.get("KEEP_SYSTEM", "2"))
RUN_AS_DEV = os.environ.get("RUN_AS_DEV", "1").lower() in {"1", "true", "yes"}


# -------------------- Development or Production --------------------
if RUN_AS_DEV:  # Development mode: enable CORS, no static hosting
    app = Flask(__name__)
    CORS(app)

else:  # Production mode: serve static files from Vite build
    # 关闭 werkzeug 自带的访问日志
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)  # 只输出错误日志(不打印普通请求)
    
    # 让 Flask 直接把 dist 当静态根目录
    app = Flask(__name__, static_folder="dist", static_url_path="/")
    
    # 静态前端路由：不是 /api 的都交给 index.html
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def catch_all(path):
        # /api/* 由后端处理；其余路径返回前端入口
        if path.startswith("api/"):
            return ("Not Found", 404)
        return send_from_directory(app.static_folder, "index.html")
    

# -------------------- Connect to Vector DB --------------------
if USE_VEC_DB:
    # initialize WeaviateMemory
    memory_store = None
    try:
        # Initialize the client once, globally
        memory_store = WeaviateMemory(openai_key=os.environ.get("OPENAI_API_KEY"))

    except Exception as e:
        print(f"WARNING: Failed to initialize WeaviateMemory client: {e}")
        print(f"Use SimpleMemory instead.")
        USE_VEC_DB = False # Disable if connection fails


# -------------------- Model & Orchestrator & Metadata --------------------
_llm = init_llm(TOOLS)
_invoke = make_app(_llm, TOOLS)

print(f"Memory: Short{'+Long' if USE_LTM else ''} | Max context scale: {MAX_TURNS}")
print(f"Running Mode: {'Development' if RUN_AS_DEV else 'Production'}")

# -------------------- endpoints --------------------

@app.get("/api/healthz")
def healthz():
    return {"ok": True, "use_ltm": USE_LTM, "use_vec_db": USE_VEC_DB, "cached_sessions": len(CACHED_SESSIONS.cache)}


@app.post("/api/create_user")
def create_user():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400

    user_id = gen_id("u")
    identity_token = uuid.uuid4().hex + uuid.uuid4().hex  # long random
    token_h = sha256(identity_token)

    #  初始化用户的memory sharing网络
    ensure_user_rel(user_id)
    save_relationships()

    # update metadata
    USER_NAME_MAP[user_id] = name

    # create dirs and files
    udir = user_dir(user_id)
    ensure_dir(os.path.join(udir, "sessions"))
    write_json(user_meta_path(user_id), {
        "user_id": user_id,
        "name": name,
        "description": description,
        "created_at": now()
    })
    with open(user_token_hash_path(user_id), "w", encoding="utf-8") as f:
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
                mem = SimpleMemory(path=user_memory_path(user_id))
                if name:
                    mem.remember(f"User name: {name}", kind="profile", meta={})
                if description:
                    mem.remember(f"User description: {description}", kind="profile", meta={})
            except Exception:
                print(f"Error remembering profile for user {user_id}: {e}")
                ensure_dir(udir)
                open(user_memory_path(user_id), "a", encoding="utf-8").close()

    return jsonify({"user_id": user_id, "identity_token": identity_token})


@app.post("/api/create_session")
def create_session():
    user_id = auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(force=True)
    session_name = (data.get("session_name") or "").strip() or f"session-{int(now())}"
    session_id = gen_id("s")
    sdir = session_dir(user_id, session_id)
    ensure_dir(sdir)
    # init state with a system message (role)
    append_session(user_id, session_id, {"type":"system", "content": role_template, "ts": now()})
    # write simple index
    write_json(os.path.join(sdir, "index.json"), {
        "session_id": session_id,
        "session_name": session_name,
        "created_at": now()
    })
    return jsonify({"session_id": session_id})


@app.get("/api/get_sessions")
def get_sessions():
    user_id = auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401

    # read user info
    username = USER_NAME_MAP.get(user_id, "User")

    # concatenate
    sroot = os.path.join(user_dir(user_id), "sessions")
    sessions = []
    if os.path.exists(sroot):
        for sid in os.listdir(sroot):
            idxp = os.path.join(sroot, sid, "index.json")
            meta = read_json(idxp, {})
            if meta:
                sessions.append(meta)
    sessions.sort(key=lambda x: x.get("created_at", 0), reverse=True)

    return jsonify({
        "user_id": user_id,
        "username": username,
        "sessions": sessions
    })


@app.get("/api/get_conversation_history")
def get_conversation_history():
    user_id = auth_user(request)
    if not user_id:
        return jsonify({"error":"unauthorized"}), 401
    session_id = request.args.get("session_id", "")
    if not session_id:
        return jsonify({"error":"session_id required"}), 400

    rows = read_session(user_id, session_id)[1:]  # Do not send the system prompt to user
    messages = [ {"type": r.get("type"), "content": r.get("content")} for r in rows ]
    return jsonify({"messages": messages})


@app.get("/api/get_relationships")
def get_relationships():
    user_id = auth_user(request)
    if not user_id: return jsonify({"error":"unauthorized"}), 401
    
    ensure_user_rel(user_id)
    raw_data = RELATIONSHIPS[user_id]
    
    # 返回 {id, name} 对象列表，而不是纯 ID 列表
    return jsonify({
        "exposed_to": enrich_user_list(raw_data["exposed_to"]),
        "amplify_from": enrich_user_list(raw_data["amplify_from"])
    })


#  严格保持数据一致性的更新接口
@app.post("/api/update_relationships")
def update_relationships():
    """
    更新当前用户的关系网。
    逻辑：维护 'Arrow' (A -> B) 的一致性。
    - A.exposed_to 包含 B <==> B.amplify_from 包含 A
    用户可以单方面切断箭头。
    """
    user_id = auth_user(request)
    if not user_id: return jsonify({"error":"unauthorized"}), 401
    
    ensure_user_rel(user_id)
    data = request.get_json(force=True)
    
    # 注意：前端发送更新时，建议仍然发送 user_id 列表，这样最安全
    # 但返回给前端的状态，我们给它包装成带 name 的格式，方便直接渲染
    try:
        update_relationships_for_user(user_id, data)
        save_relationships()
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
    # 返回更新后的状态，同时也带上 Name
    return jsonify({
        "status": "ok", 
        "current": {
            "exposed_to": enrich_user_list(RELATIONSHIPS[user_id]["exposed_to"]),
            "amplify_from": enrich_user_list(RELATIONSHIPS[user_id]["amplify_from"])
        }
    })


@app.post("/api/chat")
def chat():
    """Non-streaming chat: append user msg -> build context -> call graph -> append ai -> return last_ai.
       If you want streaming SSE, pass ?stream=1 (we simulate SSE by sending the final text once)."""
    user_id = auth_user(request)
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
    statep = session_state_path(user_id, session_id)
    append_session(user_id, session_id, {"type": message.get("type","human"), "content": message.get("content",""), "ts": now()})

    # 2) read state messages
    raw_msgs = read_session(user_id, session_id)
    msgs_lc: List[BaseMessage] = []
    for r in raw_msgs:
        msgs_lc.append(to_lc({"type": r.get("type"), "content": r.get("content")}))

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
                    snips = map_snippets_to_names(snips)
                    mem_text = format_mem_snippets(
                        snips,
                        multi_resource=(len(external_source_ids) > 0),
                        current_user_name=USER_NAME_MAP.get(user_id, user_id),
                        verbose=VERBOSE
                    )
                    
                else:
                    snips = SimpleMemory(path=user_memory_path(user_id)).retrieve(last_human, k=4, min_sim=0.55, verbose=VERBOSE)
                    mem_text = format_mem_snippets(snips, verbose=VERBOSE)

                if mem_text:
                    insert_at = 1 if msgs_lc and isinstance(msgs_lc[0], SystemMessage) else 0
                    msgs_lc = msgs_lc[:insert_at] + [SystemMessage(content=mem_text)] + msgs_lc[insert_at:]
            except Exception as e:
                print(f"Error retrieving memory for user {user_id}: {e}")

    # 4) trim context (safe) then call orchestrator
    msgs_trimmed = trim_context(msgs_lc, MAX_TURNS, keep_system=KEEP_SYSTEM)
    state_after = _invoke({"messages": msgs_trimmed})
    last_ai = next((m for m in reversed(state_after["messages"]) if isinstance(m, AIMessage)), None)
    ai_text = last_ai.content if last_ai else "[No response]"

    # 5) append AI to persistent state
    append_session(user_id, session_id, {"type": "ai", "content": ai_text, "ts": now()})

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
                SimpleMemory(path=user_memory_path(user_id)).remember(snippet, kind="turn", meta={"session_id": session_id})
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
    port = int(os.environ.get("PORT", "8080"))
    try:
        app.run(host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("\nCleaning up...")
    finally:
        if memory_store:
            memory_store.client.close()
