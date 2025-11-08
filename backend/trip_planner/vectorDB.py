# vectorDB.py
from __future__ import annotations
import os, json, time, math, re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
from langchain_core.messages import SystemMessage, HumanMessage
import numpy as np
from .llm import _get_api_key
from .memory import format_mem_snippets

import weaviate
import weaviate.classes as wvc
from weaviate.auth import AuthApiKey
from weaviate.exceptions import WeaviateQueryException

EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
WEAVIATE_CLASS_NAME = "MemoryItem"

# --------------------------- helpers ---------------------------
# _l2_normalize, _keyword_overlap, _time_decay
#
def _l2_normalize(v: np.ndarray | List[float]) -> np.ndarray:
    v = np.array(v, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / (n + 1e-12)

def _keyword_overlap(a: str, b: str) -> float:
    """极简中英混合关键词重合(Jaccard/几何平均风格)."""
    #
    tok = lambda s: set(re.findall(r"[\w\u4e00-\u9fff]+", (s or "").lower()))
    ta, tb = tok(a), tok(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / math.sqrt(len(ta) * len(tb))

def _time_decay(created_at: float, now: float, half_life_days: float = 14.0) -> float:
    """指数衰减: 越新越高, 范围约 (0.5, 1.0]."""
    #
    days = max((now - (created_at or 0.0)) / 86400.0, 0.0)
    return 0.5 ** (days / max(half_life_days, 1e-6))
# --------------------------- data types ---------------------------

@dataclass
class MemoryItem:
    id: str # Weaviate UUID
    kind: str
    text: str
    created_at: float # Unix timestamp
    meta: Dict[str, Any]

# --------------------------- store (Weaviate) ---------------------------

class WeaviateMemory:
    """
    使用 Weaviate 的长期记忆:
    - 持久化: Weaviate 实例
    - 写入: Weaviate 自动向量化 (text2vec-openai)
    - 检索: 召回(Weaviate 混合搜索) + 重排(Python 融合)
    """
    def __init__(self, url: str = "http://localhost:8080", openai_key: str | None = None):
        self.client = None
        try:
            self.client = weaviate.connect_to_local(
                host="localhost",
                port=5432,
                grpc_port=50051,
                headers={"X-OpenAI-Api-Key": openai_key or _get_api_key()}
            )
            self._ensure_schema()
        except Exception as e:
            if self.client:
                self.client.close()
            raise e

    def _ensure_schema(self):
        """确保 Weaviate Collection (Schema) 存在"""
        if not self.client.collections.exists(WEAVIATE_CLASS_NAME):
            self.client.collections.create(
                name=WEAVIATE_CLASS_NAME,
                # 使用 text2vec-openai 模块进行自动向量化
                vector_config=wvc.config.Configure.Vectors.text2vec_openai(
                    model=EMBED_MODEL,
                    vectorize_collection_name=False
                ),
                properties=[
                    wvc.config.Property(name="user_id", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="kind", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                    wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT), # 'text' 是唯一被向量化的
                    wvc.config.Property(name="created_at", data_type=wvc.config.DataType.NUMBER, skip_vectorization=True),
                    wvc.config.Property(name="meta_json", data_type=wvc.config.DataType.TEXT, skip_vectorization=True), # 存储 JSON 字符串
                ],
                # 启用 BM25 (关键词) 索引，用于混合搜索
                inverted_index_config=wvc.config.Configure.inverted_index(
                    bm25_b=0.75,
                    bm25_k1=1.2,
                )
            )
        print("[Mem] Weaviate schema ensured.")

    # --------------------- write ---------------------

    def remember(self, user_id: str, text: str, kind: str = "turn", meta: Optional[Dict[str, Any]] = None, *, max_chars: int = 800):
        """
        写入 Weaviate。
        Weaviate (非 'text' 属性) 会自动处理向量化。
        """
        text = (text or "").strip()
        if not text or not user_id:
            return
        text = text[:max_chars] # 简单裁剪
        
        # 构建 Weaviate 对象
        data_obj = {
            "user_id": user_id,
            "kind": kind,
            "text": text,
            "created_at": time.time(),
            "meta_json": json.dumps(meta or {}),
        }
        
        # 插入数据
        collection = self.client.collections.get(WEAVIATE_CLASS_NAME)
        collection.data.insert(data_obj)
        print(f"[Mem] Remembered for user {user_id}: {text[:50]}...")

    # --------------------- read (retrieve) ---------------------

    def retrieve(
        self,
        user_id: str, # 必须：用于数据隔离
        query: str,
        k: int = 4,
        min_sim: float = 0.55,
        *,
        alpha: float = 0.7,           # 语义 vs 关键词 融合比
        half_life_days: float = 14.0, # 时间衰减
        recall_limit: int = 50,      # 步骤1：召回的数量
        verbose: bool = True,
    ) -> List[Tuple[MemoryItem, float]]:
        """
        执行“召回-重排”流水线。
        """
        if not user_id:
            if verbose: print("[Mem] user_id required for retrieval.")
            return []
            
        collection = self.client.collections.get(WEAVIATE_CLASS_NAME)

        # -----------------------------------------------
        # 步骤 1: 召回 (Recall) - Weaviate
        # -----------------------------------------------
        # 使用混合搜索 (Hybrid Search): 
        # 结合向量 (语义) 和 BM25 (关键词) 进行召回
        try:
            response = collection.query.hybrid(
                query=query,
                # 过滤：只召回属于该 user_id 的记忆
                filters=wvc.query.Filter.by_property("user_id").equal(user_id),
                limit=recall_limit,
                # 'alpha=0.5' 意味着 50% 语义, 50% 关键词。
                # 注意：这是 Weaviate 的召回 alpha，不是您的重排 alpha
                alpha=0.5, 
                # 返回我们重排所需的所有属性
                return_properties=["kind", "text", "created_at", "meta_json"],
                # 返回距离 (用于计算 'cos')
                return_metadata=wvc.query.MetadataQuery(distance=True) 
            )
        except WeaviateQueryException as e:
            if verbose: print(f"[Mem] Weaviate query error: {e}")
            return []

        if not response.objects:
            if verbose: print("[Mem] Weaviate returned 0 objects.")
            return []

        # -----------------------------------------------
        # 步骤 2: 重排 (Re-rank)
        # -----------------------------------------------
        # 应用memory.py中定义的精确融合逻辑
        
        candidates = []
        now = time.time()
        
        if verbose:
            print(f"\n[Mem] query: {query!r}")
            print(f"[Mem] Reranking top {len(response.objects)} candidates for user {user_id}...")
            print("[Mem] rank | w_dist  cos   kw    td   fused | pass | preview")

        for r, obj in enumerate(response.objects, 1):
            props = obj.properties
            
            # 1) Weaviate 距离 -> 余弦相似度
            # Weaviate 的 'distance' 是余弦距离 (0=相同, 2=相反)
            # 相似度 = 1 - 距离
            cos = 1.0 - (obj.metadata.distance or 1.0)
            
            # 2) 关键词重合
            #
            kw = _keyword_overlap(query, props.get("text", "")) 
            
            # 3) 时间衰减
            #
            created_at = props.get("created_at", 0.0)
            td = _time_decay(created_at, now, half_life_days)
            
            # 4) 融合得分
            #
            base = alpha * cos + (1.0 - alpha) * kw 
            score = base * (0.85 + 0.15 * td)

            passed = score >= min_sim
            if verbose:
                preview = (props.get("text", "") or "")[:80].replace("\n", " ")
                w_dist = obj.metadata.distance or 0.0
                print(f"[Mem]  {r:<3} | {w_dist:5.2f} {cos:5.2f} {kw:5.2f} {td:5.2f} {score:6.3f} | "
                      f" {'✓' if passed else 'X'}   | {preview}...")
            
            # 构建 MemoryItem 以便返回
            item = MemoryItem(
                id=str(obj.uuid),
                kind=props.get("kind", "unknown"),
                text=props.get("text", ""),
                created_at=created_at,
                meta=json.loads(props.get("meta_json", "{}"))
            )
            candidates.append((item, score))

        # -----------------------------------------------
        # 步骤 3: 最终排序与过滤
        # -----------------------------------------------
        # 按fused_score降序排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # 过滤掉低于 min_sim 的
        #
        hits = [c for c in candidates if c[1] >= min_sim][:k]
        
        if not hits and candidates:
            if verbose:
                print(f"[Mem] no items >= min_sim({min_sim}); fallback to top-{k}.")
            # 回退到 top-k
            hits = candidates[:k] 
        
        out: List[Tuple[MemoryItem, float]] = hits
        if verbose:
            kept = ", ".join(f"{score:.3f}" for _, score in out)
            print(f"[Mem] returned {len(out)} item(s) with fused scores: [{kept}]\n")
        
        return out

# --------------------------- formatting ---------------------------
def compose_tmp_message(state: dict, mem: WeaviateMemory, user_id: str):
    """ 
    Search based on the most recent user input and return 
    a list of messages that are only valid in this round.
    
    *** 需要从 state 或上层获取 user_id ***
    """
    state_msgs = state["messages"]
    q = None
    for m in reversed(state_msgs):
        if isinstance(m, HumanMessage):
            q = m.content
            break
    if not q or not user_id: # 检查 user_id
        return state_msgs
        
    # 调用retrieve方法，传入user_id
    snips = mem.retrieve(user_id, q, k=4, min_sim=0.55) 
    
    mem_text = format_mem_snippets(snips)
    if not mem_text:
        return state_msgs

    msgs = list(state_msgs)
    insert_at = 1 if msgs and isinstance(msgs[0], SystemMessage) else 0
    msgs.insert(insert_at, SystemMessage(content=mem_text))
    return msgs
