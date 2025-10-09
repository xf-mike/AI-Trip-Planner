# export OPENAI_API_KEY=(Your own key)

cd backend
source .venv/bin/activate

SESSION=backend

if tmux has-session -t $SESSION 2>/dev/null; then
    echo "Session '$SESSION' already exists. Attaching..."
    tmux attach -t $SESSION
else
    echo "Starting new tmux session '$SESSION'..."
    tmux new -d -s $SESSION "python production.py"
fi

deactivate
clear

# (attach session tmux attach -t backend
# (detach session) (Ctrl+b, d)