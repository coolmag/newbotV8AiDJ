import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message, _heuristic_fallback
from gemini_init import genai, HAS_GENAI, GEMINI_KEY # Импорт глобальных флагов и модуля genai для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-generativeai SDK not imported or configured")

def test_analyze_message_search_intent_gemini():
    """Тестирует успешный happy-path с интентом 'search' через Gemini."""
    mock_response = Mock()
    mock_response.text = '{"intent": "search", "query": "Linkin Park Numb"}'
    
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    with patch('google.generativeai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            intent, query = analyze_message(message="play numb")
            
            mock_model_class.assert_called_once_with("gemini-pro")
            mock_model_instance.generate_content.assert_called_once()
            
            assert intent == "search"
            assert query == "Linkin Park Numb"

def test_analyze_message_chat_intent_gemini():
    """Тестирует успешный happy-path с интентом 'chat' через Gemini."""
    mock_response = Mock()
    mock_response.text = '{"intent": "chat", "query": ""}'
    
    mock_model_instance = Mock()
    mock_model_instance.generate_content.return_value = mock_response
    
    with patch('google.generativeai.GenerativeModel', return_value=mock_model_instance) as mock_model_class:
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            intent, query = analyze_message(message="how are you?")
            
            mock_model_class.assert_called_once_with("gemini-pro")
            mock_model_instance.generate_content.assert_called_once()
            
            assert intent == "chat"
            assert query == ""

def test_analyze_message_fallback_on_api_error_gemini():
    """Тестирует fallback к эвристике при ошибке Gemini API."""
    with patch('google.generativeai.GenerativeModel', side_effect=Exception("API is down")):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            # Эвристика должна сработать и вернуть "chat" для короткого сообщения без ключевых слов
            intent, query = analyze_message(message="ошибка")
            assert intent == "chat" 
            assert query == ""

def test_heuristic_fallback_short_chat_message():
    """Тестирует эвристику для короткого чат-сообщения."""
    # Используем чистую эвристику без моков Gemini
    intent, query = _heuristic_fallback("привет")
    assert intent == "chat"
    assert query == ""

def test_heuristic_fallback_short_search_message_with_keyword():
    """Тестирует эвристику для короткого поискового сообщения с ключевым словом."""
    intent, query = _heuristic_fallback("включи")
    assert intent == "search"
    assert query == "включи"

def test_heuristic_fallback_long_search_message_no_keyword():
    """Тестирует эвристику для длинного поискового сообщения без ключевого слова."""
    intent, query = _heuristic_fallback("очень длинное сообщение, которое точно больше 30 символов")
    assert intent == "search"
    assert query == "очень длинное сообщение, которое точно больше 30 символов"

@patch('gemini_init.GEMINI_KEY', None) # Мокаем отсутствие ключа внутри gemini_init
def test_analyze_message_no_api_key_global():
    """Тестирует fallback, если глобальный ключ API отсутствует."""
    with patch('gemini_init.HAS_GENAI', True): # Убеждаемся, что SDK импортирован
        intent, query = analyze_message(message="нет ключа")
        assert intent == "chat" # Эвристика по умолчанию для короткого сообщения
        assert query == ""

@patch('gemini_init.HAS_GENAI', False) # Мокаем, что SDK не импортирован
def test_analyze_message_sdk_not_imported():
    """Тестирует fallback, если SDK 'genai' не импортирован."""
    with patch('gemini_init.genai', None): # SDK не импортирован, genai=None
        intent, query = analyze_message(message="нет SDK")
        assert intent == "chat" # Эвристика по умолчанию для короткого сообщения
        assert query == ""