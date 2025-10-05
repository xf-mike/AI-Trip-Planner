from tools import TOOLS
from orchestrate import make_app
from user import CLI
from llm import init_llm
from role import role_template
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


    
def main():
    
    print("\n=== LangGraph Agent Demo — Phase 1 (IO split) ===")

    llm_invoker = init_llm(TOOLS)
    app = make_app(llm_invoker, TOOLS)
    
    print("\nType 'exit' to quit. Try: 'Plan a 2-day Tokyo trip, browse the internet for nice places and check the weather'.\n")
    
    state = {"messages": [SystemMessage(content=role_template)]}
    usr = CLI()

    while True:

        # Get input from user
        try:
            user_inp = usr.get_input()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_inp:
            continue
        if user_inp.lower() in {"exit", "quit", ":q"}:
            break

        state["messages"].append(HumanMessage(content=user_inp))

        # Get response from agent, state transition
        state = app(state)
        
        # push the agent response back to user
        last_ai = None
        for m in reversed(state["messages"]):
            if isinstance(m, AIMessage):
                last_ai = m
                break
        if last_ai is None:
            usr.send_response("[No response]")
        else:
            usr.send_response(last_ai.content)


if __name__ == "__main__":
    main()
