import os
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from context import trim_context


class MessagesState(TypedDict):
    messages: Annotated[list, add_messages]


def make_app(llm_invoke, tools: list, context_scale: int = 5):
    
    # Limit the context memory size before feeding to llm
    def call_agent(state: MessagesState) -> dict:
        msgs = trim_context(state["messages"], context_scale)
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
