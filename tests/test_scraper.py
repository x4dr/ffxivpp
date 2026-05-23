import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from bot.commands import PartyBot

@pytest.mark.asyncio
async def test_scraper_loop_priority():
    # Setup
    bot = PartyBot()
    bot.is_closed = MagicMock(side_effect=[False, True]) # Run once then stop
    
    with patch('app.db.get_next_scraper_task') as mock_get_task, \
         patch('app.db.delete_scraper_task') as mock_del_task, \
         patch('app.db.get_parties_for_lodestone_id') as mock_get_parties, \
         patch('app.db.cache_character') as mock_cache, \
         patch('app.db.db_connection') as mock_db, \
         patch('app.lodestone.fetch_character', new_callable=MagicMock) as mock_fetch, \
         patch('bot.commands.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        
        # Scenario: High priority task exists
        mock_get_task.return_value = {'lodestone_id': '123', 'priority': 1}
        # Ensure db_connection() context manager returns a mock that doesn't fail
        mock_db.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {'person_id': 1}
        
        mock_fetch.return_value = {'name': 'TestChar', 'avg_ilvl': 700}
        mock_get_parties.return_value = [] # No embed updates for test
        
        # Run scraper loop once
        await bot.scraper_loop()
        
        # Verify
        mock_fetch.assert_called_once_with('123')
        mock_del_task.assert_called_once_with('123')
        # Check if sleep was 1s (the priority interval)
        assert mock_sleep.call_args_list[0][0][0] == 1

@pytest.mark.asyncio
async def test_scraper_loop_regular():
    # Setup
    bot = PartyBot()
    bot.is_closed = MagicMock(side_effect=[False, True])
    
    with patch('app.db.get_next_scraper_task') as mock_get_task, \
         patch('app.db.db_connection') as mock_db, \
         patch('app.db.get_parties_for_lodestone_id') as mock_get_parties, \
         patch('app.db.cache_character') as mock_cache, \
         patch('app.lodestone.fetch_character', new_callable=MagicMock) as mock_fetch, \
         patch('bot.commands.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        
        # Scenario: No priority task
        mock_get_task.return_value = None
        # Mock DB response for regular task
        mock_db.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {'person_id': 1, 'lodestone_id': '456'}
        mock_fetch.return_value = {'name': 'TestChar', 'avg_ilvl': 700}
        mock_get_parties.return_value = []
        
        # Run scraper loop once
        await bot.scraper_loop()
        
        # Verify
        mock_fetch.assert_called_once_with('456')
        # Check if sleep was 10s (the regular interval)
        assert mock_sleep.call_args_list[0][0][0] == 10
