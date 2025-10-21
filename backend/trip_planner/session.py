from __future__ import annotations
import os, json, time, uuid
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from .llm import init_llm
from .orchestrate import make_app
from .tools import TOOLS, meta
from .role import role_template
from .context import trim_context
from .memory import SimpleMemory, format_mem_snippets


@dataclass
class MessageRecord:
    mem_index: int
    owner: Literal["user", "agent"]
    content: str
    gen_by_engine: bool = False
    context_size: int = 0
    use_ltm: bool = False
    memory_injected: List[int] = field(default_factory=list)
    use_tools: List[str] = field(default_factory=list)


class Session:
    """Evaluation Session (simple version)"""

    def __init__(self, background_info: Optional[str] = None,
                 session_id: Optional[str] = None,
                 root: str = "./eval_runs",
                 verbose=False):

        self.background_info = background_info
        self.root = root
        os.makedirs(os.path.join(root, "sessions"), exist_ok=True)

        if session_id:
            # Load existing session
            self.session_id = session_id
        else:
            self.session_id = f"s_{uuid.uuid4().hex[:8]}"

        self.sdir = os.path.join(root, "sessions", self.session_id)
        os.makedirs(self.sdir, exist_ok=True)
        self.history_path = os.path.join(self.sdir, "history.jsonl")
        self.mem_path = os.path.join(self.sdir, "memory.jsonl")

        # --- load or initialize history ---
        self.history: List[MessageRecord] = []
        if os.path.exists(self.history_path):
            with open(self.history_path, "r", encoding="utf-8") as f:
                for line in f:
                    self.history.append(MessageRecord(**json.loads(line)))

        # --- LTM store ---
        self.mem = SimpleMemory(self.mem_path)

        # --- initialize LLM + app ---
        self.llm = init_llm(TOOLS, verbose=verbose)
        self.app = make_app(self.llm, TOOLS)

        # --- If creating a new session with background info ---
        if background_info and not os.path.exists(self.history_path):
            # bg = MessageRecord(
            #     mem_index=0,
            #     owner="agent",
            #     content=background_info,
            #     gen_by_engine=False,
            # )
            # self._append_record(bg)
            self.mem.remember(background_info, kind="profile", meta={"mem_index": 0})

    # ------------------------------------------------------------------

    def _append_record(self, rec: MessageRecord):
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        self.history.append(rec)

    def _remember_qa_pair(self, q_text: str, a_text: str, a_mem_index: int) -> None:
        """Save a compact Q/A snippet into LTM for retrieval."""
        try:
            snippet = (f"Q: {q_text}\nA: {a_text}")[:800]
            self.mem.remember(snippet, kind="turn", meta={"mem_index": a_mem_index})
        except Exception:
            pass

    def append_message(self, content: str, owner: Literal["user", "agent"]) -> None:
        """
        Append a message verbatim (no model call).
        If this creates a (user -> agent) pair, auto-save a compact QA to LTM.
        """
        rec = MessageRecord(
            mem_index=len(self.history),
            owner=owner,
            content=content,
            gen_by_engine=False,
        )
        self._append_record(rec)

        # ---- 即时归档到 LTM：如果形成了 Q&A，就保存 ----
        # 仅当当前是 agent 且上一条是 user 时触发
        if owner == "agent" and len(self.history) >= 2:
            prev = self.history[-2]
            if prev.owner == "user":
                # 将 (prev.user -> rec.agent) 作为一对 Q&A 存入 LTM
                self._remember_qa_pair(prev.content, rec.content, rec.mem_index)

    def get_history(self) -> List[Dict[str, Any]]:
        return [asdict(r) for r in self.history]

    # ------------------------------------------------------------------

    def empty_session(self, use_ltm: bool = True) -> None:
        """
        Clears the current session's history (RAM and disk).
        Optionally resets the long-term memory (LTM).

        Params:
            use_ltm (bool):
            - True (default): Keeps the LTM. Clears chat history only.
            - False: Resets the LTM. Clears both chat history and LTM,
                     then re-initializes the LTM with the background_info.
        """
        # 1. Clear chat history (in-RAM)
        self.history = []
        
        # 2. Clear chat history (on-disk)
        try:
            if os.path.exists(self.history_path):
                os.remove(self.history_path)
        except OSError as e:
            print(f"[WARN] Could not remove history file {self.history_path}: {e}")

        # 3. Handle Long-Term Memory (LTM)
        if not use_ltm:
            # Reset LTM: delete file, re-init object, re-add background_info
            try:
                if os.path.exists(self.mem_path):
                    os.remove(self.mem_path)
            except OSError as e:
                print(f"[WARN] Could not remove memory file {self.mem_path}: {e}")
            
            # Re-instantiate the memory object (clears in-RAM store)
            self.mem = SimpleMemory(self.mem_path)
            
            # Re-add background info, mimicking __init__ logic
            if self.background_info:
                self.mem.remember(self.background_info, kind="profile", meta={"mem_index": 0})
        
        # If use_ltm is True, we do nothing to self.mem or self.mem_path.
        # The LTM persists, but the chat history is gone.

    # ------------------------------------------------------------------

    def chat(self, user_request: str, context_size: int = 6,
         use_ltm: bool = True, store_to_cache: bool = False,
             verbose: bool = False) -> str:
        """
        One chat turn. If store_to_cache=False, this call is SIDE-EFFECT FREE:
        Params:
            user_request: the new user message for this turn
            context_size: max context turns used by the model (trim_context handles details)
            use_ltm: whether to retrieve from session-scoped long-term memory
            store_to_cache:
            - Fals  => dry-run, no side effects
                * Do NOT append the user/agent messages to session history
                * Do NOT write Q&A summary to long-term memory
            - True => persist to history and LTM
                * Append both user and agent messages to history
                * Optionally write a compact Q&A summary to long-term memory
            verbose: whether to print the retrieve logs
        """
        # --- 1) Build a temporary message list for this inference only ---
        msgs = [SystemMessage(content=role_template)]
        for r in self.history:
            if r.owner == "user":
                msgs.append(HumanMessage(content=r.content))
            else:
                msgs.append(AIMessage(content=r.content))

        # LTM retrieval (read-only)
        mem_injected = []
        if use_ltm:
            try:
                snips = self.mem.retrieve(user_request, k=4, min_sim=0.55, verbose=verbose)
                for item, _ in snips:
                    idx = int(item.meta.get("mem_index", 0)) if item.meta else 0
                    mem_injected.append(idx)
                if snips:
                    mem_txt = format_mem_snippets(snips)
                    msgs.insert(1, SystemMessage(content=mem_txt))
            except Exception:
                pass

        # 临时加入本轮用户消息（仅用于推理；是否持久化看 store_to_cache）
        msgs.append(HumanMessage(content=user_request))

        # --- 2) Trim and run the graph ---
        msgs_trim = trim_context(msgs, context_size)
        n0 = len(msgs_trim)  # 调用前长度，用来切分新增片段

        original_verbose_state = meta['verbose']
        meta['verbose'] = verbose
        state = self.app({"messages": msgs_trim})
        meta['verbose'] = original_verbose_state
        
        new_msgs = state["messages"][n0:] if len(state["messages"]) >= n0 else state["messages"]

        # --- 3) Parse outputs for this turn (tools + final AI) ---
        use_tools: List[str] = []
        last_ai: Optional[AIMessage] = None

        for m in new_msgs:
            if isinstance(m, ToolMessage):
                # ToolMessage 有 name 和 content
                if getattr(m, "name", None):
                    # use_tools.append(m.name)
                    use_tools.append({"name": m.name, "output": m.content})
            elif isinstance(m, AIMessage):
                last_ai = m  # 最后一个 AIMessage 作为最终回复

        # # optional: 去重工具名，保持出现顺序
        # seen = set()
        # use_tools = [x for x in use_tools if not (x in seen or seen.add(x))]

        resp_text = last_ai.content if last_ai else "[No response]"

        arec = MessageRecord(
            mem_index=len(self.history),
            owner="agent",
            content=resp_text,
            gen_by_engine=True,
            context_size=context_size,
            use_ltm=use_ltm,
            memory_injected=mem_injected,
            use_tools=use_tools,
        )
        
        # --- 4) Side effects only when store_to_cache=True ---
        if store_to_cache:
            # 先写入本轮 user record
            urec = MessageRecord(
                mem_index=len(self.history),
                owner="user",
                content=user_request
            )
            self._append_record(urec)

            # 再写入本轮 agent record
            self._append_record(arec)

            # 写入 LTM 的摘要
            try:
                snippet = (f"Q: {user_request}\nA: {resp_text}")[:800]
                self.mem.remember(snippet, kind="turn", meta={"mem_index": arec.mem_index})
            except Exception:
                pass

        return asdict(arec)
