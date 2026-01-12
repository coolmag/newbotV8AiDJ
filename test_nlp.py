import pytest
from unittest.mock import Mock, patch

# Импортируем функцию для тестирования
from nlp import analyze_message, genai
from config import Settings

# Пропускаем все тесты в этом файле, если SDK не установлен
pytestmark = pytest.mark.skipif(not genai, reason="google-genai SDK not installed")

def test_analyze_message_success():
    """Тестирует happy-path с правильным моком для синхронной функции."""
    mock_response = Mock()
    mock_response.text = '{"intent": "radio", "query": "энергичные русские хиты"}'
    
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    with patch('google.genai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        # Передаем settings и сообщение
        intent, query = analyze_message(settings, "давай давай")
        
        mock_model_class.assert_called_once_with("gemini-1.5-flash")
        mock_model_instance.generate_content.assert_called_once()
        
        assert intent == "radio"
        assert query == "энергичные русские хиты"

def test_analyze_message_fallback_on_error():
    """Тестирует fallback при ошибке API."""
    with patch('google.genai.GenerativeModel', side_effect=Exception("API is down")):
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = analyze_message(settings, "любой запрос")
        
        assert intent == "search"
        assert query == "любой запрос"

def test_analyze_message_no_api_key():
    """Тестирует fallback, если ключ API отсутствует."""
    settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY=None)
    
    intent, query = analyze_message(settings, "тестовый запрос")
    
    assert intent == "search"
    assert query == "тестовый запрос"
