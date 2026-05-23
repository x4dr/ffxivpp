import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
from bot.commands import PersistentPartyView

@pytest.mark.asyncio
async def test_embed_status_generation():
    # Mock data
    party_name = "TestParty"
    target_ilvl = 600
    now = datetime.now(timezone.utc)
    
    # Test cases: (days_old, ilvl, expected_substring)
    test_cases = [
        (4, 500, "Outdated (4 days)"), # Outdated AND low gear
        (1, 500, "Low Gear (Current: 500 / Target: 600)"), # Recent AND low gear
        (1, 650, None), # Recent AND high gear -> No warning
    ]
    
    for days_old, ilvl, expected in test_cases:
        fetched_at = (now - timedelta(days=days_old)).isoformat()
        
        with patch('bot.commands.get_party_members') as mock_members, \
             patch('bot.commands.get_cached_character') as mock_cache, \
             patch('bot.commands.constraints_from_db') as mock_constraints:
            
            mock_members.return_value = [{'name': 'User', 'lodestone_id': '123', 'jobs': ['tank']}]
            mock_cache.return_value = {'fetched_at': fetched_at, 'avg_ilvl': ilvl}
            mock_constraints.return_value = {'min_gear_level': target_ilvl}
            
            view = PersistentPartyView()
            channel = MagicMock()
            message = MagicMock()
            message.embeds = [MagicMock(title=f"Party: {party_name}")]
            
            # This is a bit tricky since update_embed is async and does network IO
            # We would need to mock channel.edit for this to fully work
            # For this test, we can just check the logic by mocking the dependent functions
            
            # Since update_embed is complex, focusing on logic:
            # Let's just call the logic in a way that doesn't trigger the edit
            # Actually, I will just test the string generation logic directly if I could refactor it.
            # As is, I'll mock edit to avoid network/api issues.
            message.edit = MagicMock()
            
            await view.update_embed(channel, message)
            
            # Get the description from the embed passed to edit
            embed = message.edit.call_args[1]['embed']
            description = embed.description
            
            if expected:
                assert expected in description
            else:
                assert "Outdated" not in description and "Low Gear" not in description

@pytest.mark.asyncio
async def test_missing_lodestone_data():
    with patch('bot.commands.get_party_members') as mock_members, \
         patch('bot.commands.get_cached_character') as mock_cache:
        
        mock_members.return_value = [{'name': 'User', 'lodestone_id': '123', 'jobs': ['tank']}]
        mock_cache.return_value = None
        
        view = PersistentPartyView()
        channel = MagicMock()
        message = MagicMock()
        message.embeds = [MagicMock(title=f"Party: Test")]
        message.edit = MagicMock()
        
        await view.update_embed(channel, message)
        
        embed = message.edit.call_args[1]['embed']
        assert "[no data]" in embed.description
