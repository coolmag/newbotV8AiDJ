import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message, _heuristic_fallback
from gemini_init import client, HAS_GENAI # Импорт глобальных флагов и клиента genai для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-genai SDK not imported or configured")

def test_analyze_message_search_intent():
    """Тестирует успешный happy-path с интентом 'search'."""
    mock_response = Mock()
    mock_response.text = '{"intent": "search", "query": "Linkin Park Numb"}'
    
    mock_client_instance = Mock()
    mock_client_instance.models.generate_content.return_value = mock_response
    
    with patch('gemini_init.client', mock_client_instance):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.client', mock_client_instance): # Ensure client is mocked globally
            
            intent, query = analyze_message(message="play numb")
            
            mock_client_instance.models.generate_content.assert_called_once_with(
                model='gemini-2.0-flash-exp',
                contents="Analyze this user message: \"play numb\"\n\nClassify into 3 INTENTS:\n1. \"search\" -> Request for specific song/artist.\n2. \"radio\" -> Request for genre/vibe.\n3. \"chat\" -> Conversational/greetings.\n\nReturn JSON ONLY:\n{\"intent\": \"search\"|\"radio\"|\"chat\", \"query\": \"search query or empty\"}"
            )
            
            assert intent == "search"
            assert query == "Linkin Park Numb"

def test_analyze_message_chat_intent():
    """Тестирует успешный happy-path с интентом 'chat'."""
    mock_response = Mock()
    mock_response.text = '{"intent": "chat", "query": ""}'
    
    mock_client_instance = Mock()
    mock_client_instance.models.generate_content.return_value = mock_response
    
    with patch('gemini_init.client', mock_client_instance):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.client', mock_client_instance):
            
            intent, query = analyze_message(message="how are you?")
            
            mock_client_instance.models.generate_content.assert_called_once_with(
                model='gemini-2.0-flash-exp',
                contents="Analyze this user message: \"how are you?\"\n\nClassify into 3 INTENTS:\n1. \"search\" -> Request for specific song/artist.\n2. \"radio\" -> Request for genre/vibe.\n3. \"chat\" -> Conversational/greetings.\n\nReturn JSON ONLY:\n{\"intent\": \"search\"|\"radio\"|\"chat\", \"query\": \"search query or empty\"}"
            )
            
            assert intent == "chat"
            assert query == ""

def test_analyze_message_fallback_on_api_error():
    """Тестирует fallback к эвристике при ошибке Gemini API."""
    mock_client_instance = Mock()
    mock_client_instance.models.generate_content.side_effect = Exception("API is down")

    with patch('gemini_init.client', mock_client_instance):
        with patch('gemini_init.HAS_GENAI', True), \
             patch('gemini_init.client', mock_client_instance):
            
            intent, query = analyze_message(message="ошибка")
            assert intent == "chat" # Default fallback is chat now
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
    with patch('gemini_init.client', None): # SDK не импортирован, client=None
        intent, query = analyze_message(message="нет SDK")
        assert intent == "chat" # Эвристика по умолчанию для короткого сообщения
        assert query == ""