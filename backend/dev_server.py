# server.py
# Minimal multi-user + multi-session backend (Flask)
# Endpoints:
#   POST /api/create_user                -> { user_id, identity_token }
#   POST /api/create_session             -> { session_id }
#   GET  /api/get_sessions               -> [ {session_id, session_name, created_at}, ...] (newest first)
#   GET  /api/get_conversation_history   -> { messages: [...] }
#   POST /api/chat                       -> { last_ai: {type:"ai", content:"..."} }  (optionally stream=1 to SSE)
#
# Storage layout (under ./data):
#   ./data/user_data/<user_id>/user.meta.json
#   ./data/user_data/<user_id>/memory.jsonl           # long-term memory shared across sessions
#   ./data/user_data/<user_id>/sessions/<session_id>/state.jsonl
#
# Notes:
# - Identity: client keeps identity_token; server stores only its sha256.
# - Very light error handling; no DB/locks; single-process friendly.
# - USE_LTM=1 enables memory injection & writeback; otherwise off.
# - If context.trim_context exists, we call it; else we pass messages as-is.

from __future__ import annotations
import os, json, time, uuid, hashlib
from typing import Any, Dict, List, Optional

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# your project modules
from trip_planner.orchestrate import make_app
from trip_planner.tools import TOOLS
from trip_planner.llm import init_llm
from trip_planner.role import role_template

# optional memory + context (graceful fallback if missing)
try:
    from trip_planner.memory import SimpleMemory, format_mem_snippets
except Exception:
    SimpleMemory = None
    format_mem_snippets = None

try:
    from trip_planner.context import trim_context as _trim_context
except Exception:
    _trim_context = None

# langchain message types
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage

# -------------------- config --------------------
DATA_ROOT = os.environ.get("DATA_ROOT", "./data")
USE_LTM = os.environ.get("USE_LTM", "0").lower() in {"1", "true", "yes"}
VERBOSE = os.environ.get("VERBOSE", "1").lower() in {"1", "true", "yes"}
MAX_TURNS = int(os.environ.get("MAX_TURNS_IN_CONTEXT", "16"))
KEEP_SYSTEM = int(os.environ.get("KEEP_SYSTEM", "2"))

app = Flask(__name__)
CORS(app)

# model & orchestrator (stateless)
_llm = init_llm(TOOLS)
_invoke = make_app(_llm, TOOLS)

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
        # 使用你项目里的安全裁剪（块级/必保最近 human）
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

# -------------------- endpoints --------------------

@app.get("/api/healthz")
def healthz():
    return {"ok": True, "use_ltm": USE_LTM}

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

    # init memory with name/description (if memory module available)
    if SimpleMemory is not None:
        try:
            mem = SimpleMemory(path=_user_memory_path(user_id))
            if name:
                mem.remember(f"User name: {name}", kind="profile", meta={})
            if description:
                mem.remember(f"User description: {description}", kind="profile", meta={})
        except Exception:
            pass
    else:
        # at least create empty file
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
    user_meta = _read_json(_user_meta_path(user_id), {})
    username = user_meta.get("name", "User")

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
    if USE_LTM and SimpleMemory is not None:
        last_human = None
        for m in reversed(msgs_lc):
            if isinstance(m, HumanMessage):
                last_human = m.content; break
        if last_human:
            try:
                mem = SimpleMemory(path=_user_memory_path(user_id))
                snips = mem.retrieve(last_human, k=4, min_sim=0.55, verbose=VERBOSE)
                if snips:
                    mem_text = format_mem_snippets(snips)
                    insert_at = 1 if msgs_lc and isinstance(msgs_lc[0], SystemMessage) else 0
                    msgs_lc = msgs_lc[:insert_at] + [SystemMessage(content=mem_text)] + msgs_lc[insert_at:]
            except Exception:
                pass

    # 4) trim context (safe) then call orchestrator
    msgs_trimmed = _trim(msgs_lc)
    state_after = _invoke({"messages": msgs_trimmed})
    last_ai = next((m for m in reversed(state_after["messages"]) if isinstance(m, AIMessage)), None)
    ai_text = last_ai.content if last_ai else "[No response]"

    # 5) append AI to persistent state
    _append_jsonl(statep, {"type": "ai", "content": ai_text, "ts": _now()})

    # 6) optional: write to long term memory
    if USE_LTM and SimpleMemory is not None:
        try:
            mem = SimpleMemory(path=_user_memory_path(user_id))
            last_user = message.get("content","")
            snippet = (f"Q: {last_user}\nA: {ai_text}")[:800]
            mem.remember(snippet, kind="turn", meta={"session_id": session_id})
        except Exception:
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
    app.run(host="0.0.0.0", port=port)
