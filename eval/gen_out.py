import os
import sys
import json
from pathlib import Path
import logging

# Test Phase 1 scenario
USE_LTM = False

# --- Path Setup ---
# 1. Get the directory of this script (run_eval.py), which is /.../eval/
script_dir = Path(__file__).parent

# 2. Get the project root (one level up), which is /.../
project_root = script_dir.parent

# 3. Add the project root to sys.path so we can import 'backend.trip_planner.session'
sys.path.insert(0, str(project_root))

try:
    from backend.trip_planner.session import Session
except ImportError:
    print(f"Error: Could not import 'backend.trip_planner.session'.")
    print(f"Attempted to add project root '{project_root}' to sys.path.")
    print("Please ensure 'backend/trip_planner/session.py' exists.")
    sys.exit(1)

# --- Configuration ---
TEST_REQUESTS_DIR = script_dir / "test_requests"
DEFAULT_CONTEXT_SIZE = 10 # Use a reasonable default context size
LOG = logging.getLogger(__name__)

def process_test_file(test_file_path: Path):
    """
    Loads a standard .test.json file, runs the conversation,
    and saves the agent's final response to a .out.json file.
    """
    # --- NEW: SKIP LOGIC ---
    # 1. Determine output path
    new_name = test_file_path.name.replace(".test.json", ".out.json")
    output_file_path = test_file_path.with_name(new_name)
    
    # 2. Check if output file already exists
    if output_file_path.exists():
        print(f"  [SKIP] Output already exists: {output_file_path.name}")
        return
    # --- END: SKIP LOGIC ---

    print(f"  Processing: {test_file_path.name}")

    # 1. Load the test case
    try:
        with open(test_file_path, 'r', encoding='utf-8') as f:
            test_case = json.load(f)
        
        background = test_case["background_info"]
        conversation = test_case["conversation"]
        
        if not conversation:
            print(f"    [SKIP] No conversation found in {test_file_path.name}.")
            return

    except (IOError, json.JSONDecodeError, KeyError) as e:
        print(f"    [ERROR] Failed to load or parse {test_file_path.name}: {e}")
        return

    try:
        # 2. Initialize a fresh session
        sess = Session(background_info=background)

        if conversation[-1].get("owner") != "user":
            print(f"    [WARN] Last turn in {test_file_path.name} is not 'user'. Ignore it.")
            conversation.pop(-1)

        # 3. Replay history (all turns except the last user message)
        for turn in conversation[:-1]:
            sess.append_message(content=turn["content"], owner=turn["owner"])

        # 4. Get the final user request and run chat
        final_user_request = conversation[-1]["content"]

        # 5. Get the agent's response data from history
        # We set store_to_cache=True so the user/agent turns from this 'chat'
        # call are added to the history, allowing get_history()[-1] to work.
        agent_response = sess.chat(
            user_request=final_user_request,
            context_size=DEFAULT_CONTEXT_SIZE,
            use_ltm=USE_LTM,
            store_to_cache=True, # <-- Set to True
            verbose=False
        )

        # 6. Prepare the output data
        output_data = {
            "response": agent_response,
            "evaluate": {} # Placeholder for the judger
        }

        # 7. Write to the .out.json file (path already calculated above)
        with open(output_file_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"    -> Saved: {output_file_path.name}")

    except Exception as e:
        # Check if the error is the recursion limit
        if "Recursion limit" in str(e):
            print(f"    [ERROR] Recursion limit reached. Agent may be in a loop.")
            print(f"            Error details: {e}")
        else:
            print(f"    [ERROR] Unhandled exception while processing {test_file_path.name}: {e}")


def process_inter_session_test_file(test_file_path: Path):
    """
    Loads an inter-session .test.json file (with 'previous_conversation'),
    runs both sessions, and saves the final response.
    """
    # --- NEW: SKIP LOGIC ---
    # 1. Determine output path
    new_name = test_file_path.name.replace(".test.json", ".out.json")
    output_file_path = test_file_path.with_name(new_name)
    
    # 2. Check if output file already exists
    if output_file_path.exists():
        print(f"  [SKIP] Output already exists: {output_file_path.name}")
        return
    # --- END: SKIP LOGIC ---

    print(f"  Processing Inter-Session: {test_file_path.name}")

    # 1. Load the test case
    try:
        with open(test_file_path, 'r', encoding='utf-8') as f:
            test_case = json.load(f)
        
        background = test_case["background_info"]
        prev_conversation = test_case["previous_conversation"]
        new_conversation = test_case["conversation"]
        
        if not prev_conversation or not new_conversation:
            print(f"    [SKIP] 'previous_conversation' or 'conversation' is missing/empty.")
            return

    except (IOError, json.JSONDecodeError, KeyError) as e:
        print(f"    [ERROR] Failed to load or parse {test_file_path.name}: {e}")
        return

    try:
        # --- PHASE 1: Run "Previous" Session to populate LTM ---
        sess = Session(background_info=background)

        # Replay ALL turns from the previous conversation
        # append_message will automatically save Q/A pairs to LTM
        for turn in prev_conversation:
            sess.append_message(content=turn["content"], owner=turn["owner"])
        
        print(f"    - Phase 1 (LTM) complete. {len(prev_conversation)} turns processed.")

        # --- PHASE 2: Start "New" Session, keeping LTM ---
        # This clears chat history but keeps the LTM file
        sess.empty_session(use_ltm=USE_LTM)
        print(f"    - Phase 2 (empty_session) complete. LTM kept.")

        # --- PHASE 3: Run "New" Conversation ---
        # Replay history (all turns except the last user message)
        if new_conversation[-1].get("owner") != "user":
            print(f"    [WARN] Last turn in {test_file_path.name} is not 'user'. Ignore it.")
            new_conversation.pop(-1)

        for turn in new_conversation[:-1]:
            sess.append_message(content=turn["content"], owner=turn["owner"])

        # Get the final user request and run chat
        final_user_request = new_conversation[-1]["content"]

        # 5. Get the agent's response data from history
        # We set store_to_cache=True to persist this final turn
        agent_response = sess.chat(
            user_request=final_user_request,
            context_size=DEFAULT_CONTEXT_SIZE,
            use_ltm=USE_LTM,
            store_to_cache=True, # <-- Set to True
            verbose=False
        )

        # 6. Prepare the output data
        output_data = {
            "response": agent_response,
            "evaluate": {} # Placeholder for the judger
        }

        # 7. Write to the .out.json file (path already calculated above)
        with open(output_file_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"    -> Saved: {output_file_path.name}")

    except Exception as e:
        if "Recursion limit" in str(e):
            print(f"    [ERROR] Recursion limit reached. Agent may be in a loop.")
            print(f"            Error details: {e}")
        else:
            print(f"    [ERROR] Unhandled exception while processing {test_file_path.name}: {e}")


def main():
    """
    Main function to find and process all .test.json files.
    """
    print(f"Starting output generation...")
    print(f"Looking for tests in: {TEST_REQUESTS_DIR}\n")

    if not TEST_REQUESTS_DIR.is_dir():
        print(f"Error: Test directory not found: {TEST_REQUESTS_DIR}")
        return

    # Iterate through each subdirectory (e.g., "1-User_Prefer")
    for test_dir in sorted(TEST_REQUESTS_DIR.iterdir()):
        if not test_dir.is_dir():
            continue
        
        print(f"--- Processing directory: {test_dir.name} ---")
        
        # Find all .test.json files
        test_files = sorted(list(test_dir.glob("*.test.json")))
        
        if not test_files:
            print("  No .test.json files found.")
            continue
            
        for test_file in test_files:
            # --- NEW LOGIC ---
            # Check directory name to call the correct processor
            if test_dir.name == "8-Inter_Session":
                process_inter_session_test_file(test_file)
            else:
                process_test_file(test_file)

    print("\n---  Output generation run complete. ---")

if __name__ == "__main__":
    main()