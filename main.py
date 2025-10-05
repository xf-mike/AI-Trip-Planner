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
from langgraph.graph import StateGraph, START, END
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


# ──────────────────────────────────────────────────────────────────────────────
# Tools — real HTTP-backed implementations (Wikipedia & DuckDuckGo; Open-Meteo)
# Notes:
#   * No API keys required
#   * Keep short timeouts; return concise strings for model friendliness
#   * If an API fails, degrade gracefully to a helpful message
# ──────────────────────────────────────────────────────────────────────────────

import requests
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "LangGraph-Demo/1.0 (+https://example.local)"}

@tool("search_tool")
def search_tool(query: str) -> str:
    """Search the web for a concise answer/snippet (Wikipedia→DuckDuckGo fallback).

    Args:
        query: natural language query.
    Returns:
        A short textual snippet.
    """
    print("[INFO] search_tool is called. Executing...")
    
    q = query.strip()
    try:
        # 1) Wikipedia summary API (best-effort)
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(q),
            headers=UA,
            timeout=4,
        )
        if r.status_code == 200:
            data = r.json()
            # Prefer 'extract' (plain-text summary)
            extract = data.get("extract")
            if extract:
                title = data.get("title", "Wikipedia")
                return f"{title}: {extract}"
    except Exception:
        pass

    try:
        # 2) DuckDuckGo Instant Answer API
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers=UA,
            timeout=4,
        )
        if r.status_code == 200:
            data = r.json()
            abstract = data.get("AbstractText")
            if abstract:
                return abstract
            heading = data.get("Heading")
            if heading:
                return heading
    except Exception:
        pass

    return f"[search] No concise result for: {q}. Try rephrasing or a more specific query."


def _parse_date_label(date_label: str) -> str:
    now = datetime.now(timezone.utc)
    dl = (date_label or "today").strip().lower()
    if dl in {"today", "now"}:
        d = now
    elif dl in {"tomorrow", "tmr"}:
        d = now + timedelta(days=1)
    else:
        # Try ISO-like date
        try:
            d = datetime.fromisoformat(dl).replace(tzinfo=timezone.utc)
        except Exception:
            d = now
    return d.strftime("%Y-%m-%d")


@tool("weather_tool")
def weather_tool(city: str, date: str = "today") -> str:
    """Get simple weather (Open-Meteo). Supports 'today'/'tomorrow' or ISO date.

    Args:
        city: e.g., 'Tokyo' or 'Kyoto'.
        date: 'today' | 'tomorrow' | 'YYYY-MM-DD'.
    Returns:
        A concise weather sentence.
    """
    print("[INFO] weather_tool is called. Executing...")
    
    city_q = (city or "").strip()
    if not city_q:
        return "[weather] Please provide a city name."

    try:
        # Geocoding → lat/lon
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city_q, "count": 1, "language": "en"},
            headers=UA,
            timeout=4,
        )
        if geo.status_code != 200:
            return f"[weather] Geocoding failed for {city_q}."
        g = geo.json()
        results = g.get("results") or []
        if not results:
            return f"[weather] City not found: {city_q}."
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        canonical = results[0].get("name", city_q)
        country = results[0].get("country", "")

        # Date handling
        target = _parse_date_label(date)

        # Daily forecast
        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "UTC",
                "start_date": target,
                "end_date": target,
            },
            headers=UA,
            timeout=4,
        )
        if fc.status_code != 200:
            return f"[weather] Forecast fetch failed for {canonical}."
        d = fc.json()
        daily = d.get("daily", {})
        dates = daily.get("time", [])
        if not dates:
            return f"[weather] No forecast data for {canonical} on {target}."

        tmax = daily.get("temperature_2m_max", [None])[0]
        tmin = daily.get("temperature_2m_min", [None])[0]
        rain = daily.get("precipitation_sum", [None])[0]
        code = daily.get("weathercode", [None])[0]

        desc_map = {
            0: "clear",
            1: "mainly clear",
            2: "partly cloudy",
            3: "overcast",
            45: "fog",
            48: "depositing rime fog",
            51: "light drizzle",
            53: "drizzle",
            55: "dense drizzle",
            61: "light rain",
            63: "rain",
            65: "heavy rain",
            71: "light snow",
            73: "snow",
            75: "heavy snow",
            80: "rain showers",
            81: "heavy showers",
            95: "thunderstorm",
        }
        desc = desc_map.get(code, "mixed conditions")
        rain_txt = f", precip {rain}mm" if rain is not None else ""
        return f"Weather in {canonical}{' ('+country+')' if country else ''} on {target}: {desc}, min {tmin}°C / max {tmax}°C{rain_txt}."

    except Exception as e:
        return f"[weather] Error: {e}"


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
        state = app.invoke(state)
        # 'result' contains the reduced state after this step
        # keep rolling state for the session

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
