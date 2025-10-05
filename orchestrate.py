import os
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition


class MessagesState(TypedDict):
    messages: Annotated[list, add_messages]


def trim_context(msgs, max_n):
    # Keep last max_n, but ensure we don't start with a ToolMessage without
    # its preceding assistant tool_call (OpenAI API constraint).
    if len(msgs) > max_n:
        msgs = msgs[-max_n:]
    # Drop any leading ToolMessage(s) to avoid orphan tool outputs
    try:
        from langchain_core.messages import ToolMessage
    except Exception:
        ToolMessage = None
    if ToolMessage is not None:
        while msgs and isinstance(msgs[0], ToolMessage):
            msgs = msgs[1:]
    return msgs

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
