from unittest.mock import AsyncMock, MagicMock, patch

from bot.commands import PartyBot


async def test_scraper_loop_priority():
    # Setup
    bot = PartyBot()
    bot.is_closed = MagicMock(side_effect=[False, True]) # Run once then stop

    with patch('app.db.get_next_scraper_task') as mock_get_task, \
         patch('app.db.delete_scraper_task') as mock_del_task, \
         patch('app.db.get_parties_for_lodestone_id') as mock_get_parties, \
          patch('app.db.cache_character') as mock_cache, \
          patch('app.db.Session') as mock_session, \
          patch('app.lodestone.fetch_character', new_callable=MagicMock) as mock_fetch, \
          patch('bot.commands.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:


        # Scenario: High priority task exists
        mock_get_task.return_value = {'lodestone_id': '123', 'priority': 1}
        # Mock Session to return a LodestoneLink with person_id=1
        mock_session.query.return_value.filter_by.return_value.first.return_value = MagicMock(person_id=1)

        mock_fetch.return_value = {'name': 'TestChar', 'avg_ilvl': 700}
        mock_get_parties.return_value = [] # No embed updates for test

        # Run scraper loop once
        await bot.scraper_loop()

        # Verify
        mock_fetch.assert_called_once_with('123')
        mock_del_task.assert_called_once_with('123')
        mock_session.remove.assert_called()
        # Check if sleep was 1s (the priority interval)
        assert mock_sleep.call_args_list[0][0][0] == 10

async def test_scraper_loop_regular():
    # Setup
    bot = PartyBot()
    bot.is_closed = MagicMock(side_effect=[False, True])

    with patch('app.db.get_next_scraper_task') as mock_get_task, \
         patch('app.db.Session') as mock_session, \
         patch('app.db.get_parties_for_lodestone_id') as mock_get_parties, \
         patch('app.db.cache_character') as mock_cache, \
         patch('app.lodestone.fetch_character', new_callable=MagicMock) as mock_fetch, \
         patch('bot.commands.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:

        # Scenario: No priority task
        mock_get_task.return_value = None
        # Mock Session to return a LodestoneLink with person_id=1, lodestone_id='456'
        mock_session.query.return_value.order_by.return_value.first.return_value = MagicMock(person_id=1, lodestone_id='456')
        mock_fetch.return_value = {'name': 'TestChar', 'avg_ilvl': 700}
        mock_get_parties.return_value = []

        # Run scraper loop once
        await bot.scraper_loop()

        # Verify
        mock_fetch.assert_called_once_with('456')
        mock_session.remove.assert_called()
        # Check if sleep was 10s (the regular interval)
        assert mock_sleep.call_args_list[0][0][0] == 10
