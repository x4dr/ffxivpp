import os
import subprocess
import time

import requests


def test_server_lifecycle():
    print("Starting server process...")
    start_time = time.time()

    # Start the server (simulating how it's currently done)
    env = os.environ.copy()
    env["FLASK_APP"] = "app"
    env["FLASK_ENV"] = "testing"
    env["PYTHONUNBUFFERED"] = "1"
    env["DATABASE_PATH"] = "test_lifecycle.db"
    env["TEST_MOCK_AUTH"] = "1"

    process = subprocess.Popen(
        [".venv/bin/python3", "app.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for startup
    startup_time = None
    for _ in range(10):
        try:
            requests.get("http://127.0.0.1:7111")
            startup_time = time.time()
            print(f"Server started in {startup_time - start_time:.2f} seconds.")
            break
        except requests.exceptions.ConnectionError:
            time.sleep(1)
    else:
        print("Server failed to start.")
        process.kill()
        return

    # Wait a second as requested
    time.sleep(1)

    # Terminate
    print("Terminating server...")
    terminate_start = time.time()
    process.terminate()
    try:
        process.wait(timeout=5)
        terminate_end = time.time()
        print(f"Server terminated in {terminate_end - terminate_start:.2f} seconds.")
    except subprocess.TimeoutExpired:
        print("Termination timed out, killing...")
        kill_start = time.time()
        process.kill()
        process.wait()
        kill_end = time.time()
        print(f"Server killed in {kill_end - kill_start:.2f} seconds.")

    print(f"Total lifecycle duration: {time.time() - start_time:.2f} seconds.")

if __name__ == "__main__":
    test_server_lifecycle()
