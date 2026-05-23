import pytest
from unittest.mock import patch, MagicMock
from app.lodestone import fetch_character

# Mock response for character main page
class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.text = content
        self.status_code = status_code
    def json(self): return {}

def test_fetch_character_from_fixture():
    # Load fixtures
    with open('tests/fixtures/character_anonymized.html', 'r') as f:
        main_html = f.read()
    with open('tests/fixtures/tooltip_anonymized.html', 'r') as f:
        tool_html = f.read()

    def mocked_get(url, **kwargs):
        if 'equipment/tooltip/0' in url:
            return MockResponse(tool_html)
        return MockResponse(main_html)

    with patch('requests.get', side_effect=mocked_get):
        # We need to bypass cache or make sure it's fresh
        # Since we use fetch_character, it checks the DB. 
        # For testing, let's mock the DB too, or just use a temporary DB
        with patch('app.db.get_cached_character', return_value=None), \
             patch('app.db.cache_character', return_value=None):
            data = fetch_character('00000000')
            assert data['name'] == 'Anonymized User'
            assert data['avg_ilvl'] is not None
