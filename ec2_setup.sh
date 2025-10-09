sudo apt update
sudo apt install -y npm
cd frontend/
npm i
npm run build
rm -rf ../backend/dist
mv dist ../backend/
cd ../backend/
sudo apt install -y python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
clear
