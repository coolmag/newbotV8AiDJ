import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message, genai
from config import Settings
from main import HAS_GENAI, GEMINI_KEY # Импорт глобальных флагов для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-genai SDK not installed or configured")

def test_analyze_message_success():
    """Тестирует happy-path с моком genai.GenerativeModel."""
    mock_response = Mock()
    mock_response.text = '{"intent": "radio", "query": "энергичные хиты"}'
    
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    with patch('google.genai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key") # Ключ нужен для внутренней проверки
        
        # Передаем settings и сообщение
        intent, query = analyze_message(message="давай давай", settings=settings)
        
        mock_model_class.assert_called_once_with("gemini-1.5-flash")
        mock_model_instance.generate_content.assert_called_once()
        
        assert intent == "radio"
        assert query == "энергичные хиты"

def test_analyze_message_fallback_on_error():
    """Тестирует fallback при ошибке API."""
    with patch('google.genai.GenerativeModel', side_effect=Exception("API is down")):
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        
        intent, query = analyze_message(message="ошибка", settings=settings)
        
        assert intent == "search"
        assert query == "ошибка"

def test_analyze_message_no_api_key():
    """Тестирует fallback, если ключ API отсутствует (симулируем через settings)."""
    settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY=None)
    
    intent, query = analyze_message(message="нет ключа", settings=settings)
    
    assert intent == "search"
    assert query == "нет ключа"

def test_analyze_message_sdk_not_installed():
    """Тестирует fallback, если SDK 'genai' не установлен (симулируем)."""
    # Мокаем HAS_GENAI как False, чтобы симулировать отсутствие SDK
    with patch('main.HAS_GENAI', False):
        settings = Settings(BOT_TOKEN="test", GEMINI_API_KEY="fake-key")
        intent, query = analyze_message(message="нет SDK", settings=settings)
        assert intent == "search"
        assert query == "нет SDK"
