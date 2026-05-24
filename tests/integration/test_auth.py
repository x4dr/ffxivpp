import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from flask import Flask

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent.resolve()))

from app.auth import check_access

@pytest.fixture
def mock_auth():
    with patch("app.auth.get_discord") as mock_get_discord, \
         patch("app.auth.bot_owner_id") as mock_bot_owner, \
         patch("app.auth._bot_api") as mock_bot_api, \
         patch("app.auth.get_role_ids") as mock_get_role_ids:
        
        discord = MagicMock()
        mock_get_discord.return_value = discord
        
        yield {
            "discord": discord,
            "bot_owner": mock_bot_owner,
            "bot_api": mock_bot_api,
            "get_role_ids": mock_get_role_ids
        }

def test_scenario_1_admin_owner(mock_auth):
    # Authorized=True, Owner=True, Member=True
    mock_auth["discord"].authorized = True
    mock_auth["discord"].fetch_user.return_value.id = "123"
    mock_auth["bot_owner"].return_value = "123"
    
    assert check_access() is True

def test_scenario_2_party_member(mock_auth):
    # Authorized=True, Owner=False, Member=True
    mock_auth["discord"].authorized = True
    mock_auth["discord"].fetch_user.return_value.id = "456"
    mock_auth["bot_owner"].return_value = "123"
    
    # Guild owner is not user
    mock_auth["bot_api"].side_effect = [
        {"owner_id": "789"}, # /guilds/{guild_id}
        {"roles": ["100"]}    # /guilds/{guild_id}/members/{user_id}
    ]
    
    mock_auth["get_role_ids"].return_value = {"100"}
    
    assert check_access() is True

def test_scenario_3_auth_no_access(mock_auth):
    # Authorized=True, Owner=False, Member=False
    mock_auth["discord"].authorized = True
    mock_auth["discord"].fetch_user.return_value.id = "456"
    mock_auth["bot_owner"].return_value = "123"
    
    # Guild owner is not user
    mock_auth["bot_api"].side_effect = [
        {"owner_id": "789"}, # /guilds/{guild_id}
        {"roles": ["200"]}    # /guilds/{guild_id}/members/{user_id}
    ]
    
    mock_auth["get_role_ids"].return_value = {"100"}
    
    assert check_access() is False

def test_scenario_4_unauthorized(mock_auth):
    # Authorized=False
    mock_auth["discord"].authorized = False
    
    assert check_access() is False
