import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message
from main import genai, HAS_GENAI, GEMINI_KEY # Импорт глобальных флагов и модуля genai для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-genai SDK not imported or configured")

def test_analyze_message_success():
    """Тестирует happy-path с моком genai.GenerativeModel."""
    mock_response = Mock()
    mock_response.text = '{"intent": "radio", "query": "энергичные хиты"}'
    
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    # Патчим класс GenerativeModel в модуле 'genai' (глобально доступный)
    with patch('google.genai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        # Мокаем глобальные переменные для nlp
        with patch('nlp.HAS_GENAI', True), \
             patch('nlp.GEMINI_KEY', "fake-key"):
            
            # Передаем только сообщение
            intent, query = analyze_message(message="давай давай")
            
            mock_model_class.assert_called_once_with("gemini-1.5-flash")
            mock_model_instance.generate_content.assert_called_once()
            
            assert intent == "radio"
            assert query == "энергичные хиты"

def test_analyze_message_fallback_on_error():
    """Тестирует fallback при ошибке API."""
    with patch('google.genai.GenerativeModel', side_effect=Exception("API is down")):
        # Мокаем глобальные переменные для nlp
        with patch('nlp.HAS_GENAI', True), \
             patch('nlp.GEMINI_KEY', "fake-key"):
            
            intent, query = analyze_message(message="ошибка")
            assert intent == "search"
            assert query == "ошибка"

@patch('nlp.GEMINI_KEY', None) # Мокаем отсутствие ключа внутри nlp
def test_analyze_message_no_api_key_global():
    """Тестирует fallback, если глобальный ключ API отсутствует."""
    with patch('nlp.HAS_GENAI', True): # Убеждаемся, что SDK импортирован
        intent, query = analyze_message(message="нет ключа")
        assert intent == "search"
        assert query == "нет ключа"

@patch('nlp.HAS_GENAI', False) # Мокаем, что SDK не импортирован
def test_analyze_message_sdk_not_imported():
    """Тестирует fallback, если SDK 'genai' не импортирован."""
    intent, query = analyze_message(message="нет SDK")
    assert intent == "search"
    assert query == "нет SDK"
