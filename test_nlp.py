import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message, _heuristic_fallback
from gemini_init import genai, HAS_GENAI, GEMINI_KEY # Импорт глобальных флагов и модуля genai для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-generativeai SDK not imported or configured")

def test_analyze_message_search_intent():
    """Тестирует успешный happy-path с интентом 'search'."""
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

def test_analyze_message_chat_intent():
    """Тестирует успешный happy-path с интентом 'chat'."""
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

def test_analyze_message_fallback_on_api_error():
    """Тестирует fallback при ошибке API."""
    with patch('google.generativeai.GenerativeModel', side_effect=Exception("API is down")):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            intent, query = analyze_message(message="ошибка")
            assert intent == "chat" # Default fallback is chat now
            assert query == ""

def test_analyze_message_fallback_to_heuristic_short_message():
    """Тестирует fallback к эвристике для короткого сообщения."""
    # Мокаем ошибку от GenerativeModel
    with patch('google.generativeai.GenerativeModel', side_effect=Exception("Model not found")):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            intent, query = analyze_message(message="привет") # Короткое сообщение
            assert intent == "chat"
            assert query == ""

def test_analyze_message_fallback_to_heuristic_long_message_with_keywords():
    """Тестирует fallback к поиску для длинного сообщения с ключевыми словами."""
    # Мокаем ошибку от GenerativeModel
    with patch('google.generativeai.GenerativeModel', side_effect=Exception("Model not found")):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            intent, query = analyze_message(message="включи мне песню про любовь")
            assert intent == "search"
            assert query == "включи мне песню про любовь"

def test_analyze_message_fallback_to_heuristic_long_message_no_keywords():
    """Тестирует fallback к поиску для длинного сообщения без ключевых слов (длиннее 30)."""
    with patch('google.generativeai.GenerativeModel', side_effect=Exception("Model not found")):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.GEMINI_KEY', "fake-key"), \
             patch('gemini_init.genai', genai):
            
            intent, query = analyze_message(message="ну как там дела в космосе вообще все хорошо или не очень я переживаю")
            assert intent == "search"
            assert query == "ну как там дела в космосе вообще все хорошо или не очень я переживаю"

@patch('gemini_init.GEMINI_KEY', None) # Мокаем отсутствие ключа внутри gemini_init
def test_analyze_message_no_api_key_global():
    """Тестирует fallback, если глобальный ключ API отсутствует."""
    with patch('gemini_init.HAS_GENAI', True): # Убеждаемся, что SDK импортирован
        intent, query = analyze_message(message="нет ключа")
        assert intent == "chat" # Default fallback is chat if no key and short message
        assert query == ""

@patch('gemini_init.HAS_GENAI', False) # Мокаем, что SDK не импортирован
def test_analyze_message_sdk_not_imported():
    """Тестирует fallback, если SDK 'genai' не импортирован."""
    with patch('gemini_init.genai', None): # SDK не импортирован, genai=None
        intent, query = analyze_message(message="нет SDK")
        assert intent == "chat" # Default fallback is chat if no SDK and short message
        assert query == ""