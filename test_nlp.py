import pytest
from unittest.mock import AsyncMock, patch
from nlp import analyze_message
from config import Settings

@pytest.mark.asyncio
async def test_analyze_message_with_gemini():
    """Тестирует успешный happy-path с ответом от Gemini."""
    # Мокаем ответ от модели Gemini
    mock_model = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = '{"intent": "radio", "query": "rock mix"}'
    mock_model.generate_content_async.return_value = mock_response
    
    # Патчим саму модель и ключ API
    with patch('nlp.genai.GenerativeModel', return_value=mock_model), \
         patch('config.Settings.GEMINI_API_KEY', "fake-key"):

        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key") 
        intent, query = await analyze_message("включи рок", settings)
        
        assert intent == "radio"
        assert query == "rock mix"
        mock_model.generate_content_async.assert_called_once()

@pytest.mark.asyncio
async def test_analyze_message_fallback_on_no_key():
    """Тестирует fallback-логику, если ключ API отсутствует."""
    settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY=None) # Явно нет ключа
    
    intent, query = await analyze_message("test query", settings)
    
    assert intent == "search"
    assert query == "test query"

@pytest.mark.asyncio
async def test_analyze_message_fallback_on_api_error():
    """Тестирует fallback-логику при ошибке API."""
    mock_model = AsyncMock()
    mock_model.generate_content_async.side_effect = Exception("API is down")
    
    with patch('nlp.genai.GenerativeModel', return_value=mock_model), \
         patch('config.Settings.GEMINI_API_KEY', "fake-key"):

        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        intent, query = await analyze_message("some query", settings)
        
        assert intent == "search"
        assert query == "some query"

@pytest.mark.asyncio
async def test_analyze_message_fallback_on_bad_json():
    """Тестирует fallback, если Gemini вернул некорректный JSON."""
    mock_model = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = 'this is not json'
    mock_model.generate_content_async.return_value = mock_response
    
    with patch('nlp.genai.GenerativeModel', return_value=mock_model), \
         patch('config.Settings.GEMINI_API_KEY', "fake-key"):

        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        intent, query = await analyze_message("bad json query", settings)
        
        assert intent == "search"
        assert query == "bad json query"
