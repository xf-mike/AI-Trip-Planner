## Backend for AI Trip Planner: V1

### How to run the backend server on bare Linux / WSL

1. uv venv
2. source .venv/bin/activate
3. uv pip install -r requirements.txt
4. export OPENAI_API_KEY=************** (Your own key)
5. export USE_LTM=1 (if you want to use long term memory)
6. python app.py
7. deactivate (close the virtual environment after running)
