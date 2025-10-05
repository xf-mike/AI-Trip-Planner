# ──────────────────────────────────────────────────────────────────────────────
# LangGraph Agent Demo — Phase 1 Baseline
# ──────────────────────────────────────────────────────────────────────────────
# This is a minimal, runnable LangGraph agent that can use two tools (search &
# weather). It keeps only in-session messages (short-term context) and does NOT
# implement any long-term memory yet — perfect as a Phase 1 baseline.
#
# Project layout (all in this single file for the first step):
#   - requirements (as comments)
#   - tool implementations
#   - graph (agent node + tool node + routing)
#   - CLI runner
#
# To run:
#   1) pip install -U langgraph langchain langchain-openai pydantic
#   2) export OPENAI_API_KEY=sk-...
#   3) python this_file.py
#
# Once this works, we can refactor into a package structure and add memory in
# Phase 2 (vector store + retrieval + summarization + tool-instruction pruning).
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import time
from typing import Annotated, TypedDict, Literal

# LangGraph core
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

# LangChain core types
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
    AIMessage,
)
from langchain_core.tools import tool

# OpenAI chat model wrapper for LangChain
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END


# ──────────────────────────────────────────────────────────────────────────────
# Tools (Phase 1: simple, deterministic stubs so the graph runs anywhere)
# Later we can replace with real HTTP APIs or your own backends.
# ──────────────────────────────────────────────────────────────────────────────

@tool("search_tool")
def search_tool(query: str) -> str:
    """Search the web or a knowledge base for a short answer. (Stub)

    Args:
        query: What to search for.
    Returns:
        A brief textual result (stubbed here for demo).
    """
    # In Phase 1 baseline, keep it deterministic & offline-friendly.
    # Replace with your real search connector later.
    print("search_tool is called. Executing...")
    
    canned = {
        "tokyo must-see": "Senso-ji, Meiji Shrine, Tokyo Skytree, Shibuya Crossing, TeamLab Planets.",
        "kyoto temples": "Kiyomizu-dera, Fushimi Inari Taisha, Kinkaku-ji, Ginkaku-ji, Ryoan-ji.",
    }
    # Super simple match; real impl: send HTTP request to your search API.
    for k, v in canned.items():
        if k in query.lower():
            return v
    return f"[search_stub] No direct match. Try refining: '{query}'."


@tool("weather_tool")
def weather_tool(city: str, date: str = "today") -> str:
    """Get weather for a city on a given date. (Stub)

    Args:
        city: City name (e.g., 'Tokyo').
        date: Natural language date like 'today'/'tomorrow' or '2025-10-05'.
    Returns:
        A short weather string (stubbed).
    """
    print("weather_tool is called. Executing...")
    
    city_l = city.strip().lower()
    if city_l in {"tokyo", "kyoto", "osaka"}:
        return f"Weather for {city.title()} on {date}: mild, partly cloudy, chance of showers in the evening."
    return f"Weather for {city.title()} on {date}: data unavailable in stub."

TOOLS = [search_tool, weather_tool]


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0"))
MAX_TURNS_IN_CONTEXT = int(os.environ.get("MAX_TURNS_IN_CONTEXT", "12"))


# ──────────────────────────────────────────────────────────────────────────────
# State & Nodes
# ──────────────────────────────────────────────────────────────────────────────

class MessagesState(TypedDict):
    # Use LangGraph's add_messages reducer so we can keep a list of chat turns.
    messages: Annotated[list, add_messages]

# Initialize model and bind tools (enables function-calling to these tools)
llm = ChatOpenAI(model=MODEL, temperature=TEMPERATURE, api_key=open("API_KEY", "r").read())
llm_with_tools = llm.bind_tools(TOOLS)


def call_agent(state: MessagesState) -> dict:
    """Agent node: sends the running chat transcript to the model.

    Phase 1 rule: keep only the *recent* N turns to simulate limited short-term
    context. This establishes a clear baseline before we add memory in Phase 2.
    """
    msgs = state["messages"]

    # Keep at most the last MAX_TURNS_IN_CONTEXT messages (simple baseline)
    if len(msgs) > MAX_TURNS_IN_CONTEXT:
        msgs = msgs[-MAX_TURNS_IN_CONTEXT:]

    ai = llm_with_tools.invoke(msgs)
    return {"messages": [ai]}



# ──────────────────────────────────────────────────────────────────────────────
# Simple CLI runner (single-user, single-session for Phase 1 demo)
# ──────────────────────────────────────────────────────────────────────────────

def banner():
    print("\n\n=== LangGraph Agent Demo — Phase 1 Baseline ===")
    print(f"Model: {MODEL}  |  Temp: {TEMPERATURE}  |  Max in-session turns: {MAX_TURNS_IN_CONTEXT}")
    print("Tools: search_tool, weather_tool (stubs)\n")
    print("Type 'exit' to quit. Ask e.g.: 'Plan a 2-day Tokyo trip and check the weather'.\n")


def run_cli(app):
    banner()
    # System prompt keeps the agent concise and tool-aware
    state: MessagesState = {
        "messages": [
            SystemMessage(
                content=(
                    "You are a helpful travel planner. Use tools when needed. "
                    "Keep answers concise and actionable."
                )
            )
        ]
    }

    while True:
        try:
            user_inp = input("User > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()  # newline
            break
        if not user_inp:
            continue
        if user_inp.lower() in {"exit", "quit", ":q"}:
            break

        state["messages"].append(HumanMessage(content=user_inp))

        # Run one turn of the graph
        result = app.invoke(state)
        # 'result' contains the reduced state after this step
        state = result  # keep rolling state for the session

        # Find the last AI message to print
        last_ai = None
        for m in reversed(state["messages"]):
            if isinstance(m, AIMessage):
                last_ai = m
                break
        if last_ai is None:
            print("Assistant > [No response]")
            continue

        print(f"Assistant > {last_ai.content}\n")


if __name__ == "__main__":
    
    if not os.path.exists("API_KEY"):
        print("[ERROR] Please set OPENAI_API_KEY in your environment.")
        sys.exit(1)

    # Build the graph
    builder = StateGraph(MessagesState)

    builder.add_node("agent", call_agent)
    # Prebuilt ToolNode executes all tool calls produced by the last AIMessage
    builder.add_node("tools", ToolNode(TOOLS))

    # Route after agent: if it requested tools → go to tools; else → END
    builder.add_conditional_edges(
        "agent",
        tools_condition,  # inspect last AIMessage for tool_calls
        {"tools": "tools", "__end__": END},
    )

    # After tools execute, go back to the agent with tool results appended
    builder.add_edge("tools", "agent")

    # Entry point
    builder.add_edge(START, "agent")

    # Compile graph into an app
    app = builder.compile()

    # run the CLI
    run_cli(app)
