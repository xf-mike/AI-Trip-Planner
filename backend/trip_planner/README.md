### How to run it on bare Linux / WSL

1. uv venv
2. source .venv/bin/activate
3. uv pip install -r requirements.txt
4. export OPENAI_API_KEY=************** (Your own key)
5. export USE_LTM=1 (if you want to use long term memory)
6. cd ..
7. python -m  trip_planner.main
8. deactivate (close the virtual environment after running)


### How to run it on Docker

1. docker build -t langgraph-demo:phase1 .
2. export OPENAI_API_KEY=************** (Your own key)
3. docker run -it --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e USE_LTM=1 \
  langgraph-demo:phase1
