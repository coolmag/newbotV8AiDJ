import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message, heuristic # Импорт heuristic для прямого тестирования
from gemini_init import client, HAS_GENAI # Импорт клиента и HAS_GENAI для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-genai SDK not installed or configured")

def test_analyze_message_search_intent():
    """Тестирует успешный happy-path с интентом 'search'."""
    mock_response = Mock()
    mock_response.text = '{"intent": "search", "query": "Linkin Park Numb"}'
    
    # Мокаем client.models.generate_content
    mock_client_models = Mock()
    mock_client_models.generate_content.return_value = mock_response
    
    mock_client_instance = Mock()
    mock_client_instance.models = mock_client_models

    with patch('gemini_init.client', mock_client_instance):
        with patch('gemini_init.HAS_GENAI', True):
            intent, query = analyze_message(message="play numb")
            
            mock_client_models.generate_content.assert_called_once_with(
                model='gemini-2.0-flash-exp', # Модель как в nlp.py
                contents="Analyze this user message: \"play numb\"\n\nClassify into 3 INTENTS:\n1. \"search\" -> Request for specific song/artist.\n2. \"radio\" -> Request for genre/vibe.\n3. \"chat\" -> Conversational/greetings.\n\nReturn JSON ONLY:\n{\"intent\": \"search\"|\"radio\"|\"chat\", \"query\": \"search query or empty\"}"
            )
            
            assert intent == "search"
            assert query == "Linkin Park Numb"

def test_analyze_message_chat_intent():
    """Тестирует успешный happy-path с интентом 'chat'."""
    mock_response = Mock()
    mock_response.text = '{"intent": "chat", "query": ""}'
    
    mock_client_models = Mock()
    mock_client_models.generate_content.return_value = mock_response
    
    mock_client_instance = Mock()
    mock_client_instance.models = mock_client_models

    with patch('gemini_init.client', mock_client_instance):
        with patch('gemini_init.HAS_GENAI', True):
            intent, query = analyze_message(message="how are you?")
            
            mock_client_models.generate_content.assert_called_once_with(
                model='gemini-2.0-flash-exp', # Модель как в nlp.py
                contents="Analyze this user message: \"how are you?\"\n\nClassify into 3 INTENTS:\n1. \"search\" -> Request for specific song/artist.\n2. \"radio\" -> Request for genre/vibe.\n3. \"chat\" -> Conversational/greetings.\n\nReturn JSON ONLY:\n{\"intent\": \"search\"|\"radio\"|\"chat\", \"query\": \"search query or empty\"}"
            )
            
            assert intent == "chat"
            assert query == ""

def test_analyze_message_fallback_on_api_error():
    """Тестирует fallback к эвристике при ошибке Gemini API."""
    mock_client_models = Mock()
    mock_client_models.generate_content.side_effect = Exception("API is down")

    mock_client_instance = Mock()
    mock_client_instance.models = mock_client_models

    with patch('gemini_init.client', mock_client_instance):
        with patch('gemini_init.HAS_GENAI', True):
            with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic: # Мокаем heuristic
                intent, query = analyze_message(message="ошибка")
                mock_heuristic.assert_called_once()
                assert intent == "chat" 
                assert query == ""

def test_heuristic_fallback_search_intent():
    """Тестирует heuristic для поискового запроса."""
    intent, query = heuristic(message="включи рок")
    assert intent == "search"
    assert query == "включи рок"

def test_heuristic_fallback_chat_intent_short():
    """Тестирует heuristic для короткого чат-сообщения."""
    intent, query = heuristic(message="привет")
    assert intent == "chat"
    assert query == ""

def test_heuristic_fallback_chat_intent_long_no_keywords():
    """Тестирует heuristic для длинного чат-сообщения без ключевых слов."""
    intent, query = heuristic(message="очень длинное сообщение, которое точно больше 30 симворов")
    assert intent == "search" # Длинное сообщение без ключевых слов считается поиском
    assert query == "очень длинное сообщение, которое точно больше 30 симворов"

@patch('gemini_init.client', None) # Мокаем, что клиент не инициализирован
def test_analyze_message_no_client_global():
    """Тестирует, что analyze_message вызывает heuristic, если клиент не инициализирован."""
    with patch('gemini_init.HAS_GENAI', True): # Убеждаемся, что SDK импортирован
        with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic: # Мокаем heuristic
            intent, query = analyze_message(message="нет клиента")
            mock_heuristic.assert_called_once()
            assert intent == "chat"
            assert query == ""

@patch('gemini_init.HAS_GENAI', False) # Мокаем, что SDK не импортирован
def test_analyze_message_sdk_not_imported():
    """Тестирует, что analyze_message вызывает heuristic, если SDK 'genai' не импортирован."""
    with patch('gemini_init.client', None): # SDK не импортирован, client=None
        with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic: # Мокаем heuristic
            intent, query = analyze_message(message="нет SDK")
            mock_heuristic.assert_called_once()
            assert intent == "chat" # Эвристика по умолчанию для короткого сообщения
            assert query == ""
