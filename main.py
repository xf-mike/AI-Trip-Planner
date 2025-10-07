import os
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from tools import TOOLS
from orchestrate import make_app
from user import CLI
from llm import init_llm
from role import role_template
from memory import SimpleMemory, compose_tmp_message


def main():

    print("\n=== LangGraph Agent Demo — Phase 1 (short/long-term memory supported) ===")

    # LLM
    llm_invoker = init_llm(TOOLS)

    # Memory Instantiation
    state = {"messages": [SystemMessage(content=role_template)]}  # Short-term memory
    USE_LTM = os.environ.get("USE_LTM", "0").lower() in {"1", "true", "yes"}
    mem = SimpleMemory(path="memory_store.jsonl") if USE_LTM else None  # Long-term memory

    # Context Scale Setting
    MAX_CONTEXT_SCALE = int(os.environ.get("MAX_TURNS_IN_CONTEXT", "5"))
    print(f"Memory: Short{'+Long' if USE_LTM else ''} | Max context scale: {MAX_CONTEXT_SCALE}")

    # Orchestrate
    app = make_app(llm_invoker, TOOLS, MAX_CONTEXT_SCALE)

    print("\nType 'exit' to quit. Try: 'Plan a 2-day trip to San Diego, browse the internet for nice places and check the weather'.\n")
    
    # User Interface
    usr = CLI()

    while True:

        # --------------------------- Get input from user ---------------------------
        
        try:
            user_inp = usr.get_input()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_inp.lower() in {"exit", "quit", ":q"}:
            break
        if not user_inp:
            continue

        # Write the current user input to short-term memory
        state["messages"].append(HumanMessage(content=user_inp))

        # --------------------------- Get response & update memory ---------------------------
        
        if not USE_LTM:  # No Long Term Memory
            state = app(state)
            last_ai = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)

        else:  # LSTM

            # 1) In current round only, inject the "memory search results" into a temporary messages
            temp_state = {"messages": compose_tmp_message(state, mem)}

            # 2) State transition, call orchestrator (app is stateless)
            temp_state = app(temp_state)

            # 3) Find the last AI-Message from the response
            last_ai = next((m for m in reversed(temp_state["messages"]) if isinstance(m, AIMessage)), None)

            if last_ai:

                # 4) Inject this AI-Message into the real state (short-term memory)
                state["messages"].append(last_ai)

                # 5) Write to long-term memory (save short summaries/atomic memories
                # simply crop here, can also use summarize and save again)
                try:
                    snippet = (f"Q: {user_inp}\nA: {last_ai.content}")[:800]
                    mem.remember(snippet, kind="turn", meta={})
                except Exception:
                    pass
                
        # --------------------------- Send response to the user ---------------------------
        
        if last_ai:
            usr.send_response(last_ai.content)
        else:
            usr.send_response("[No response]")


if __name__ == "__main__":
    main()
