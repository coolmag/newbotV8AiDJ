import pytest
from unittest.mock import Mock, patch

# Импортируем функцию для тестирования
from nlp import analyze_message, genai
from main import HAS_GENAI, GEMINI_KEY # Импорт глобальных флагов для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not genai, reason="google-genai SDK not installed or configured")

def test_analyze_message_success():
    """Тестирует happy-path с моком genai.GenerativeModel."""
    mock_response = Mock()
    mock_response.text = '{"intent": "radio", "query": "энергичные хиты"}'
    
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    # Патчим класс GenerativeModel в модуле 'genai'
    with patch('google.genai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        # Для этого теста нам не нужен объект Settings, так как genai авто-конфигурируется
        
        # Передаем только сообщение
        intent, query = analyze_message(message="давай давай")
        
        mock_model_class.assert_called_once_with("gemini-1.5-flash")
        mock_model_instance.generate_content.assert_called_once()
        
        assert intent == "radio"
        assert query == "энергичные хиты"

def test_analyze_message_fallback_on_error():
    """Тестирует fallback при ошибке API."""
    with patch('google.genai.GenerativeModel', side_effect=Exception("API is down")):
        intent, query = analyze_message(message="ошибка")
        assert intent == "search"
        assert query == "ошибка"

@patch('main.GEMINI_KEY', None) # Мокаем отсутствие ключа
def test_analyze_message_no_api_key_global():
    """Тестирует fallback, если глобальный ключ API отсутствует."""
    intent, query = analyze_message(message="нет ключа")
    assert intent == "search"
    assert query == "нет ключа"

@patch('main.HAS_GENAI', False) # Мокаем, что SDK не импортирован
def test_analyze_message_sdk_not_imported():
    """Тестирует fallback, если SDK 'genai' не импортирован."""
    intent, query = analyze_message(message="нет SDK")
    assert intent == "search"
    assert query == "нет SDK"