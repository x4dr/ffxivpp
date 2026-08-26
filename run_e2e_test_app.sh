#!/bin/bash

# Configuration
export DATABASE_PATH="test_e2e.db"
export TEST_MOCK_AUTH="1"
export FLASK_APP="app"
export FLASK_ENV="testing"
export PYTHONUNBUFFERED="1"
export TEST_SERVER_URL="http://127.0.0.1:7111"

# Cleanup function
cleanup() {
    echo "Stopping test server (PID: $SERVER_PID)..."
    kill $SERVER_PID
    wait $SERVER_PID 2>/dev/null
    
    echo "Cleaning up browser processes..."
    pkill -f chromium || true
    
    if [ -f "$DATABASE_PATH" ]; then
        rm "$DATABASE_PATH"
    fi
    echo "Cleanup complete."
}

# Trap exit signals to ensure cleanup
trap cleanup EXIT

# Start the server
echo "Starting test server..."
.venv/bin/python3 app.py &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to be ready at $TEST_SERVER_URL..."
for i in {1..10}; do
    if curl -s "$TEST_SERVER_URL" > /dev/null; then
        echo "Server is ready."
        break
    fi
    sleep 1
    if [ $i -eq 10 ]; then
        echo "Server failed to start."
        exit 1
    fi
done

# Run tests
echo "Running tests..."
uv run pytest tests/e2e/test_app.py
