# export OPENAI_API_KEY=(Your own key)

cd backend
source .venv/bin/activate

SESSION=backend

if tmux has-session -t $SESSION 2>/dev/null; then
    echo "Session '$SESSION' already exists. Attaching..."
    tmux attach -t $SESSION
else
    tmux new -d -s $SESSION "python app.py"
    echo "Server is running in the backgroud session '$SESSION'..."
fi

deactivate

echo "(attach session): tmux attach -t $SESSION"
echo "(detach session): (Ctrl+b, d)"