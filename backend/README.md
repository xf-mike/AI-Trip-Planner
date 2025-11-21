## Backend for AI Trip Planner: V3

### How to run the backend server on bare Linux / WSL

1. uv venv
2. source .venv/bin/activate
3. uv pip install -r requirements.txt
4. export OPENAI_API_KEY=************** (Your own key)
5. export USE_LTM=1 (if you want to use long term memory)
6. python app.py
7. deactivate (close the virtual environment after running)

### How to run it on Docker

1. cd .. 
2. docker build -t xf2000/trip-planner-app:v3 .
3. docker run -it --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -e GOOGLE_CSE_ID=$GOOGLE_CSE_ID \
  -e USE_LTM=1 \
  -e VERBOSE=1 \
  -p 8080:8080 \
  xf2000/trip-planner-app:v3

### How to push to Docker Hub
1. docker tag xf2000/trip-planner-app:v3 your-user-name/trip-planner-app:v3
2. docker push your-user-name/trip-planner-app:v3
