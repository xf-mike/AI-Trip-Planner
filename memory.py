# memory.py
from __future__ import annotations
import os, json, time, math, re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
from langchain_core.messages import SystemMessage, HumanMessage
import numpy as np
from langchain_openai import OpenAIEmbeddings
from llm import _get_api_key  # 复用你已有的取 key 逻辑

EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

# --------------------------- helpers ---------------------------

def _l2_normalize(v: np.ndarray | List[float]) -> np.ndarray:
    v = np.array(v, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / (n + 1e-12)

def _keyword_overlap(a: str, b: str) -> float:
    """极简中英混合关键词重合(Jaccard/几何平均风格)."""
    tok = lambda s: set(re.findall(r"[\w\u4e00-\u9fff]+", (s or "").lower()))
    ta, tb = tok(a), tok(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / math.sqrt(len(ta) * len(tb))

def _time_decay(created_at: float, now: float, half_life_days: float = 14.0) -> float:
    """指数衰减: 越新越高, 范围约 (0.5, 1.0]."""
    days = max((now - (created_at or 0.0)) / 86400.0, 0.0)
    return 0.5 ** (days / max(half_life_days, 1e-6))

# --------------------------- data types ---------------------------

@dataclass
class MemoryItem:
    id: str
    kind: str           # "turn" | "preference" | "artifact" ...
    text: str
    created_at: float
    meta: Dict[str, Any]

# --------------------------- store ---------------------------

class SimpleMemory:
    """
    简易的长期记忆: 
    - 持久化: JSONL(每行: item + embedding)
    - 检索: 内存加载全部向量, 融合打分(语义 + 关键词 + 时间)
    """
    def __init__(self, path: str = "memory_store.jsonl"):
        self.path = path
        self._items: List[MemoryItem] = []
        self._embs: Optional[np.ndarray] = None  # shape: [N, D], L2-normalized
        self._embedder = OpenAIEmbeddings(model=EMBED_MODEL, api_key=_get_api_key())
        self._load()

    # --------------------- persistence ---------------------

    def _load(self):
        self._items = []
        embs: List[np.ndarray] = []
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    item = MemoryItem(**rec["item"])
                    emb = _l2_normalize(rec["embedding"])   # 读入即归一化
                    self._items.append(item)
                    embs.append(emb)
        self._embs = np.vstack(embs).astype(np.float32) if embs else None

    def _append(self, item: MemoryItem, emb: List[float]):
        emb = _l2_normalize(emb)                             # 写入前归一化
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"item": asdict(item), "embedding": emb.tolist()}, ensure_ascii=False) + "\n")
        # 同步内存
        self._items.append(item)
        self._embs = emb[None, :] if self._embs is None else np.vstack([self._embs, emb]).astype(np.float32)

    # --------------------- write ---------------------

    def remember(self, text: str, kind: str = "turn", meta: Optional[Dict[str, Any]] = None, *, max_chars: int = 800):
        """写入前做简单裁剪, 降低噪声.如果需要更强可在外层先做摘要."""
        text = (text or "").strip()
        if not text:
            return
        text = text[:max_chars]                               # 简单裁剪
        emb = self._embedder.embed_documents([text])[0]
        item = MemoryItem(
            id=str(int(time.time() * 1000)),
            kind=kind,
            text=text,
            created_at=time.time(),
            meta=meta or {}
        )
        self._append(item, emb)

    # --------------------- read (retrieve) ---------------------

    def retrieve(
        self,
        query: str,
        k: int = 4,
        min_sim: float = 0.55,
        *,
        alpha: float = 0.7,           # 语义 vs 关键词 融合比(0.6~0.8 常用)
        half_life_days: float = 14.0, # 时间衰减(14天半衰)
        topn_debug: int = 8,          # 打印前N个候选
        verbose: bool = True,
    ) -> List[Tuple[MemoryItem, float]]:
        """
        返回 top-k 的 (MemoryItem, fused_score).
        - 余弦相似(语义) + 关键词重合 融合, 再乘轻微时间加权.
        - 详细调试输出(cos/kw/td/fused/pass + 预览).
        - 若无命中 >= min_sim, 回退到 top-k, 方便调参观察.
        """
        if self._embs is None or not self._items:
            if verbose:
                print("[Mem] store empty — nothing to retrieve.")
            return []

        # 1) 查询向量(L2 归一化)
        qv = _l2_normalize(self._embedder.embed_query(query))

        # 2) 语义余弦(库向量已是 unit, 点积即余弦)
        cos = (self._embs @ qv).astype(np.float32)

        # 3) 关键词与时间
        kw = np.array([_keyword_overlap(query, it.text) for it in self._items], dtype=np.float32)
        now = time.time()
        td = np.array([_time_decay(it.created_at, now, half_life_days) for it in self._items], dtype=np.float32)

        # 4) 融合得分: 语义 + 关键词, 再乘时间轻权重(0.85~1.0)
        base = alpha * cos + (1.0 - alpha) * kw
        score = base * (0.85 + 0.15 * td)

        # 5) 排序 & 调试
        order = np.argsort(-score)                 # 全量降序
        top_idx = order[:max(topn_debug, k)]       # 输出更多便于观察

        if verbose:
            print(f"\n[Mem] query: {query!r}")
            print("[Mem] alpha=", alpha, "min_sim=", min_sim, "half_life_days=", half_life_days)
            print("[Mem] ---- top candidates ----")
            print("[Mem] rank |  cos   kw    td    fused | pass | preview")
            for r, i in enumerate(top_idx, 1):
                s_cos = float(cos[i]); s_kw = float(kw[i]); s_td = float(td[i]); s = float(score[i])
                passed = s >= min_sim
                preview = (self._items[i].text or "")[:80].replace("\n", " ")
                print(f"[Mem]  {r:<3} | {s_cos:5.2f} {s_kw:5.2f} {s_td:5.2f} {s:6.3f} | "
                      f" {'✓' if passed else 'X'}   | {preview}...")

        # 6) 命中选择: 优先 >= 阈值, 否则回退 top-k
        hits = [i for i in order if score[i] >= min_sim][:k]
        if not hits:
            if verbose:
                print(f"[Mem] no items >= min_sim({min_sim}); fallback to top-{k}.")
            hits = list(order[:k])

        out: List[Tuple[MemoryItem, float]] = [(self._items[i], float(score[i])) for i in hits]
        if verbose:
            kept = ", ".join(f"{float(score[i]):.3f}" for i in hits)
            print(f"[Mem] returned {len(out)} item(s) with fused scores: [{kept}]\n")
        return out

# --------------------------- formatting ---------------------------

def format_mem_snippets(snips: List[Tuple[MemoryItem, float]], max_chars: int = 800) -> str:
    """把检索结果压成短提示, 注入 SystemMessage."""
    if not snips:
        return ""
    lines: List[str] = []
    for item, sim in snips:
        lines.append(f"- ({item.kind}, {sim:.2f}) {item.text}")
        if sum(len(x) for x in lines) > max_chars:
            break
    return "Relevant prior context:\n" + "\n".join(lines)



def compose_tmp_message(state: dict, mem: SimpleMemory):
    """ Search based on the most recent user input and return 
    a list of messages that are only valid in this round."""
    # take the last one HumanMessage as query
    state_msgs = state["messages"]
    q = None
    for m in reversed(state_msgs):
        if isinstance(m, HumanMessage):
            q = m.content
            break
    if not q:
        return state_msgs
    snips = mem.retrieve(q, k=4, min_sim=0.55)
    mem_text = format_mem_snippets(snips)
    if not mem_text:
        return state_msgs

    # Insert a temporary SystemMessage after the first SystemMessage (do not write back to state)
    msgs = list(state_msgs)
    insert_at = 1 if msgs and isinstance(msgs[0], SystemMessage) else 0
    msgs.insert(insert_at, SystemMessage(content=mem_text))
    return msgs