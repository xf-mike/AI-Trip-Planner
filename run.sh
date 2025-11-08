cd frontend
npm i
npm run build
mv dist ../backend
cd ../backend
uv venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=**************
python app.py
deactivate
