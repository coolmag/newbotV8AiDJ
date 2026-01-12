import pytest
from unittest.mock import AsyncMock, patch
from config import Settings

# Импортируем функцию для тестирования
from nlp import analyze_message

@pytest.mark.asyncio
async def test_analyze_message_success():
    """Тестирует успешный happy-path с правильным импортом 'genai'."""
    # Мокаем модель и ее ответ
    mock_model_instance = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = '{"intent": "radio", "query": "энергичные русские хиты"}'
    mock_model_instance.generate_content_async.return_value = mock_response

    # Патчим класс GenerativeModel внутри модуля nlp, где он используется
    with patch('nlp.genai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = await analyze_message("давай давай", settings)
        
        # Проверяем, что GenerativeModel был инстанцирован
        mock_model_class.assert_called_once_with(model_name="gemini-1.5-flash")
        
        # Проверяем, что был вызван метод генерации
        mock_model_instance.generate_content_async.assert_called_once()
        
        # Проверяем результат
        assert intent == "radio"
        assert query == "энергичные русские хиты"

@pytest.mark.asyncio
async def test_analyze_message_fallback_on_error():
    """Тестирует fallback при ошибке API."""
    with patch('nlp.genai.GenerativeModel', side_effect=Exception("API is down")):
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = await analyze_message("любой запрос", settings)
        
        assert intent == "search"
        assert query == "любой запрос"

@pytest.mark.asyncio
async def test_analyze_message_no_api_key():
    """Тестирует fallback, если ключ API отсутствует."""
    settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY=None)
    
    intent, query = await analyze_message("тестовый запрос", settings)
    
    assert intent == "search"
    assert query == "тестовый запрос"

@pytest.mark.asyncio
async def test_analyze_message_sdk_not_installed():
    """Тестирует fallback, если SDK 'genai' не установлен."""
    with patch('nlp.genai', None): # Симулируем отсутствие модуля
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = await analyze_message("test", settings)

        assert intent == "search"
        assert query == "test"
