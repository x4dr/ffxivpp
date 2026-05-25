import pytest
import requests
import time

def test_live_server_connectivity(live_server):
    print(f"DEBUG: Testing connectivity to {live_server.url()}", flush=True)
    try:
        response = requests.get(live_server.url(), timeout=2)
        print(f"DEBUG: Response status: {response.status_code}", flush=True)
        assert response.status_code == 200
    except Exception as e:
        print(f"DEBUG: Error connecting to server: {e}", flush=True)
        raise e
