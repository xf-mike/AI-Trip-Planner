import os
from typing import List
from langchain_openai import ChatOpenAI

# ===== Runtime knobs (merged with LLM) =====
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0"))
API_KEY_PATH = os.environ.get("API_KEY_PATH", "API_KEY")


def _get_api_key() -> str:
    # Prefer env var, fallback to file (OPENAI_API_KEY)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    
    if not key and os.path.exists(API_KEY_PATH):
        with open(API_KEY_PATH, "r") as f:
            key = f.read().strip()
            if key:
                return key
    if not key:
        raise RuntimeError(
            "OpenAI API key not found. Provide file 'API_KEY' or set OPENAI_API_KEY."
        )
    return key


def init_llm(tools: List):
    """Factory returning an LLM bound with the provided tools."""
    llm = ChatOpenAI(model=MODEL, temperature=TEMPERATURE, api_key=_get_api_key())
    print(f"Model: {MODEL} | Temp: {TEMPERATURE}")
    print(f"Tools: {' | '.join(t.name for t in tools)}")
    return llm.bind_tools(tools).invoke
