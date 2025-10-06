from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from tools import TOOLS
from orchestrate import make_app
from user import CLI
from llm import init_llm
from role import role_template
from memory import SimpleMemory, format_mem_snippets


def compose_tmp_messag(state: dict, mem: SimpleMemory):
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


def main():

    print("\n=== LangGraph Agent Demo — Phase 1 (state/memory supported) ===")

    llm_invoker = init_llm(TOOLS)
    app = make_app(llm_invoker, TOOLS)

    print("\nType 'exit' to quit. Try: 'Plan a 2-day trip to San Diego, browse the internet for nice places and check the weather'.\n")

    # Memory Instantiation
    state = {"messages": [SystemMessage(content=role_template)]}  # Short-term memory
    mem = SimpleMemory(path="memory_store.jsonl")  # Long-term memory

    # User Interface
    usr = CLI()

    while True:

        # 0) Get input from user
        try:
            user_inp = usr.get_input()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_inp.lower() in {"exit", "quit", ":q"}:
            break
        if not user_inp:
            continue

        # 1) Write the current user input to state (short-term mem)
        state["messages"].append(HumanMessage(content=user_inp))

        # 2) In this round only, inject the "memory search results" into a temporary messages
        temp_state = {"messages": compose_tmp_messag(state, mem)}

        # 3) State transition, call orchestrator (app is stateless)
        temp_state = app(temp_state)

        # 4) Find the last AIMessage from the response, send it to the user
        last_ai = next((m for m in reversed(temp_state["messages"]) if isinstance(m, AIMessage)), None)
        if not last_ai:
            usr.send_response("[No response]")
            continue
        usr.send_response(last_ai.content)

        # 5) Inject this AIMessage into the real state
        state["messages"].append(last_ai)

        # 6) Write to long-term memory (save short summaries/atomic memories
        # simply crop here, can also use summarize and save again)
        try:
            snippet = (f"Q: {user_inp}\nA: {last_ai.content}")[:800]
            mem.remember(snippet, kind="turn", meta={})
        except Exception:
            pass


if __name__ == "__main__":
    main()
