#!/bin/bash
# Find and kill process running bot.py
PID=$(pgrep -f "python3 bot.py")
if [ -n "$PID" ]; then
    echo "Killing process $PID running bot.py..."
    kill $PID
    # Wait up to 5 seconds for it to die
    for i in {1..5}; do
        if ! kill -0 $PID 2>/dev/null; then
            break
        fi
        sleep 1
    done
    if kill -0 $PID 2>&1 > /dev/null; then
        echo "Process $PID still running, force killing..."
        kill -9 $PID
    fi
fi

echo "Starting bot..."
# Clear log before starting
> bot.log
export DATABASE_PATH="party.db"
nohup /home/maric/PycharmProjects/ffxivpp/.venv/bin/python3 bot.py >> bot.log 2>&1 &

echo "Bot started. Logs in bot.log"
