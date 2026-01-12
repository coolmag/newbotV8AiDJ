import pytest
from unittest.mock import Mock, patch
from nlp import analyze_message
from config import Settings

# Убираем @pytest.mark.asyncio, так как функция стала синхронной

def test_analyze_message_success():
    """Тестирует успешный happy-path с правильным моком для синхронной функции."""
    # Мокаем ответ API
    mock_response = Mock()
    mock_response.text = '{"intent": "radio", "query": "русские хиты"}'
    
    # Мокаем экземпляр модели
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    # Мокаем сам класс GenerativeModel, чтобы он возвращал наш мок
    with patch('google.genai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = analyze_message("давай нашу", settings)
        
        mock_model_class.assert_called_once_with("gemini-1.5-flash")
        mock_model_instance.generate_content.assert_called_once()
        
        assert intent == "radio"
        assert query == "русские хиты"

def test_analyze_message_fallback_on_error():
    """Тестирует fallback при ошибке API."""
    with patch('google.genai.GenerativeModel', side_effect=Exception("API is down")):
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = analyze_message("любой запрос", settings)
        
        assert intent == "search"
        assert query == "любой запрос"

def test_analyze_message_no_api_key():
    """Тестирует fallback, если ключ API отсутствует."""
    settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY=None)
    
    intent, query = analyze_message("тестовый запрос", settings)
    
    assert intent == "search"
    assert query == "тестовый запрос"