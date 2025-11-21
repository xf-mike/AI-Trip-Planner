# This version (V1) has been deprecated.
# It is kept here for reference only.
# Please refer to the latest version in `backend/app.py`.

FROM python:3.11-slim


WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Just in case of the illegal output from OpenAI API
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1


COPY . trip_planner
# Provide API key via a file named API_KEY or env OPENAI_API_KEY at runtime
CMD ["python", "-m", "trip_planner.main"]