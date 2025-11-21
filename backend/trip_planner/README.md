# This version (V1) has been deprecated.
# It is kept here for reference only.
# Please refer to the latest version in `backend/app.py`.

### How to run it on bare Linux / WSL

1. uv venv
2. source .venv/bin/activate
3. uv pip install -r requirements.txt
4. export OPENAI_API_KEY=************** (Your own key)
5. GOOGLE_API_KEY=$GOOGLE_API_KEY
6. GOOGLE_CSE_ID=$GOOGLE_CSE_ID
7. export USE_LTM=1 (if you want to use long term memory)
8. cd ..
9. python -m  trip_planner.main
10. deactivate (close the virtual environment after running)


### How to run it on Docker

1. docker build -t trip-planner:v1 .
2. export OPENAI_API_KEY=************** (Your own key)
3. docker run -it --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -e GOOGLE_CSE_ID=$GOOGLE_CSE_ID \
  -e USE_LTM=1 \
  trip-planner:v1
