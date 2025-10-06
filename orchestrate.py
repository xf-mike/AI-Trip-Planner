import os
from typing import Annotated, TypedDict, List
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage


class MessagesState(TypedDict):
    messages: Annotated[list, add_messages]


def trim_context(msgs: List[BaseMessage], max_n: int, keep_system: int = 2) -> List[BaseMessage]:
    max_n = max(int(max_n or 0), 1)
    if not msgs:
        return [SystemMessage(content="You are a helpful assistant.")]

    # 0) Take the prefix SystemMessage (usually keep 2, role template and memory
    prefix: List[BaseMessage] = []
    i = 0
    while i < len(msgs) and isinstance(msgs[i], SystemMessage) and len(prefix) < keep_system:
        prefix.append(msgs[i])
        i += 1

    # 1) Only follow-up conversations are trimmed to budget
    budget = max_n - len(prefix)
    if budget <= 0:
        return prefix[-max_n:]  # When composed entirely of system

    tail: List[BaseMessage] = msgs[i:][-budget:]

    # 2) Discard the leading orphaned ToolMessage (its preceding tool_calls has been truncated)
    while tail and isinstance(tail[0], ToolMessage):
        tail = tail[1:]

    out = prefix + tail

    # Back-up solution: If there is no System message, add one
    if not out or not isinstance(out[0], SystemMessage):
        out = [SystemMessage(content="You are a helpful assistant.")] + out
        out = out[:max_n]

    return out


def make_app(llm_invoke, tools: list):
    
    MAX_TURNS_IN_CONTEXT = int(os.environ.get("MAX_TURNS_IN_CONTEXT", "5"))
    print(f"Memory: Short | Max context turns: {MAX_TURNS_IN_CONTEXT}")

    # Limit the context memory size before feeding to llm
    def call_agent(state: MessagesState) -> dict:
        msgs = trim_context(state["messages"], MAX_TURNS_IN_CONTEXT)
        return {"messages": [llm_invoke(msgs)]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_agent)
    builder.add_node("tools", ToolNode(tools))

    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": END},  # version-compatible end key
    )
    builder.add_edge("tools", "agent")
    builder.add_edge(START, "agent")

    return builder.compile().invoke
