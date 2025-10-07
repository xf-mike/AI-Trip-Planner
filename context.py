
from typing import List, Tuple
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage


def _blocks(seq: List[BaseMessage]) -> List[Tuple[int, int]]:
    """把序列切成块: 普通块=单条. 工具块=AI(tool_calls)+后续所有ToolMessage"""
    out = []
    i = 0
    while i < len(seq):
        m = seq[i]
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            s = i
            i += 1
            while i < len(seq) and isinstance(seq[i], ToolMessage):
                i += 1
            out.append((s, i))
        else:
            out.append((i, i + 1))
            i += 1
    return out


def trim_context(
    msgs: List[BaseMessage],
    max_n: int,
    keep_system: int = 2,   # 通常 = 2: 原始 role + 记忆注入
) -> List[BaseMessage]:
    """
    Trim the chat history (message list) into a context window usable by the model.

    ───────────────────────────────────────────────────────────────────────────────
    DESIGN RATIONALE
    ───────────────────────────────────────────────────────────────────────────────
    The trimming problem in LLM-based agents is subtle because the OpenAI API
    imposes strict structural constraints on message order:

        • Every assistant message containing `tool_calls` must be immediately
          followed by the corresponding ToolMessage(s) that respond to *all*
          those `tool_call_id`s.
        • Each ToolMessage must come *after* its triggering assistant message
          (cannot appear before or stand alone).
        • The conversation must end in a consistent, complete sequence.

    Naive “take the last N messages” strategies often break these rules — e.g.
    keeping a ToolMessage without its preceding tool_call, or keeping an
    assistant(tool_calls) but dropping one of its responses — causing 400
    errors like:
        “tool_call_ids did not have response messages”.

    Meanwhile, trimming too aggressively can remove the *last user intent* or
    the *tool results* it depends on, leading to infinite tool-calling loops.

    ───────────────────────────────────────────────────────────────────────────────
    STRATEGY (pragmatic & safe)
    ───────────────────────────────────────────────────────────────────────────────
    1.  Keep up to `keep_system` SystemMessage(s) at the front
        (e.g. role prompt + injected memory summary).
        These form the stable "prefix" and are never trimmed.

    2.  Identify the most recent HumanMessage and **force-keep it and everything
        after it** (including assistant + tool messages).
        This ensures:
            - the model always sees the latest user intent;
            - all associated tool calls/results remain visible;
            - avoids the “infinite tool invocation” loop.

    3.  If that already exceeds `max_n`, stop — we'd rather go over budget than
        break conversation structure.

    4.  Otherwise, from before that last Human, walk backward *by logical blocks*:
            - a “tool block” = assistant(tool_calls) + its following ToolMessages
            - a “plain block” = any single message
        Add these blocks (from newest to oldest) until the token/length budget
        is reached or exceeded.

    5.  Finally, if no SystemMessage remains (edge case), inject a minimal
        “You are a helpful assistant.” at the top for safety.

    ───────────────────────────────────────────────────────────────────────────────
    ADVANTAGES
    ───────────────────────────────────────────────────────────────────────────────
    •  Simple, predictable, human-readable logic.
    •  Guarantees structural validity of tool call sequences.
    •  Ensures the latest human intent and its dependent results are always kept.
    •  Avoids OpenAI 400 errors (“missing tool_call responses”).
    •  Avoids infinite tool-calling loops caused by context loss.

    ───────────────────────────────────────────────────────────────────────────────
    LIMITATIONS
    ───────────────────────────────────────────────────────────────────────────────
    •  May temporarily exceed the nominal `max_n` context budget if the last
       human turn already spans many tool messages — trades efficiency for safety.
    •  If context windows are very small, earlier dialogue will be dropped more
       aggressively.
    •  Does not estimate token length — uses message count as proxy.

    This “safe over budget” heuristic is typically preferable for small projects
    or demos: correctness > strict token efficiency.

    ───────────────────────────────────────────────────────────────────────────────
    """
    max_n = max(int(max_n or 0), 1)
    if not msgs:
        return [SystemMessage(content="You are a helpful assistant.")]

    # 1) 前缀 System(不裁剪)
    prefix: List[BaseMessage] = []
    i = 0
    while i < len(msgs) and isinstance(msgs[i], SystemMessage) and len(prefix) < keep_system:
        prefix.append(msgs[i]); i += 1

    tail_all = msgs[i:]
    if not tail_all:
        out = prefix or [SystemMessage(content="You are a helpful assistant.")]
        return out[:max_n]

    # 2) 找"最近一条 Human"
    last_human = None
    for t in range(len(tail_all) - 1, -1, -1):
        if isinstance(tail_all[t], HumanMessage):
            last_human = t
            break

    # 如果没有 Human, 就按预算从结尾取块即可
    if last_human is None:
        tail_blocks = _blocks(tail_all)
        budget = max_n - len(prefix)
        chosen: List[Tuple[int, int]] = []
        total = 0
        for s, e in reversed(tail_blocks):
            L = e - s
            if total + L <= budget or not chosen:
                chosen.append((s, e)); total += L
            if total >= budget: break
        chosen.sort(key=lambda x: x[0])
        tail_out: List[BaseMessage] = []
        for s, e in chosen:
            tail_out.extend(tail_all[s:e])
        out = prefix + tail_out
        if not out or not isinstance(out[0], SystemMessage):
            out = [SystemMessage(content="You are a helpful assistant.")] + out
        return out[:max_n]

    # 3) 强制保留: 最近 Human 及其之后所有消息(避免工具自旋)
    must_keep_tail = tail_all[last_human:]        # 这段不再裁剪
    out = prefix + must_keep_tail
    if len(out) >= max_n:
        # 已经超/达预算, 直接返回(保证合法且不自旋)
        if not isinstance(out[0], SystemMessage):
            out = [SystemMessage(content="You are a helpful assistant.")] + out
        return out

    # 4) 还有预算: 从最近 Human 之前向前"按块"补上下文, 直到达到/超过预算
    head = tail_all[:last_human]
    head_blocks = _blocks(head)                   # 不跨块截断
    budget = max_n - len(out)

    prepend: List[BaseMessage] = []
    total = 0
    for s, e in reversed(head_blocks):
        L = e - s
        prepend[0:0] = head[s:e]                  # 头部插入, 保持原顺序
        total += L
        if total >= budget:
            break

    trimmed = prefix + prepend + must_keep_tail

    # 5) 兜底 System + 最终限长(只在极端情况下截掉"补上的前缀部分", 不动 must_keep_tail)
    if not trimmed or not isinstance(trimmed[0], SystemMessage):
        trimmed = [SystemMessage(content="You are a helpful assistant.")] + trimmed

    if len(trimmed) > max_n:
        # 只裁掉我们"补上的 head 前缀", 绝不动 must_keep_tail, 避免工具对被切断
        # 计算可以保留给 prepend 的空间
        space_for_prepend = max_n - (len(prefix) + len(must_keep_tail))
        if space_for_prepend < 0:
            # 极端: prefix + tail 已超预算, 仍保留它们, 丢弃 prepend
            return prefix + must_keep_tail
        # 砍掉多余的 prepend 前段
        keep_prepend = prepend[-space_for_prepend:] if space_for_prepend > 0 else []
        return prefix + keep_prepend + must_keep_tail

    return trimmed
