import pytest
from unittest.mock import Mock, patch

from nlp import analyze_message, heuristic # Импорт heuristic для прямого тестирования
from gemini_init import HAS_GENAI # Импорт HAS_GENAI для мокирования

# Пропускаем тесты, если SDK не установлен
pytestmark = pytest.mark.skipif(not HAS_GENAI, reason="google-genai SDK not imported or configured")

def test_analyze_message_success():
    """Тестирует успешный happy-path с моком generate_smart."""
    mock_generate_smart_response = '{"intent": "radio", "query": "энергичные хиты"}'
    
    with patch('gemini_init.generate_smart', return_value=mock_generate_smart_response) as mock_generate_smart:
        with patch('gemini_init.HAS_GENAI', True):
            intent, query = analyze_message(message="давай давай")
            
            mock_generate_smart.assert_called_once() # Проверяем вызов generate_smart
            
            assert intent == "radio"
            assert query == "энергичные хиты"

def test_analyze_message_fallback_on_generate_smart_none():
    """Тестирует, что analyze_message вызывает heuristic, если generate_smart возвращает None."""
    with patch('gemini_init.generate_smart', return_value=None):
        with patch('gemini_init.HAS_GENAI', True):
            with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic:
                intent, query = analyze_message(message="что угодно")
                mock_heuristic.assert_called_once()
                assert intent == "chat"
                assert query == ""

def test_analyze_message_fallback_on_generate_smart_error():
    """Тестирует, что analyze_message вызывает heuristic, если generate_smart вызывает ошибку."""
    with patch('gemini_init.generate_smart', side_effect=Exception("Generate error")):
        with patch('gemini_init.HAS_GENAI', True):
            with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic:
                intent, query = analyze_message(message="ошибка генерации")
                mock_heuristic.assert_called_once()
                assert intent == "chat"
                assert query == ""

def test_analyze_message_fallback_on_json_error():
    """Тестирует, что analyze_message вызывает heuristic, если JSON некорректен."""
    mock_generate_smart_response = "это не JSON"
    with patch('gemini_init.generate_smart', return_value=mock_generate_smart_response):
        with patch('gemini_init.HAS_GENAI', True):
            with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic:
                intent, query = analyze_message(message="неверный json")
                mock_heuristic.assert_called_once()
                assert intent == "chat"
                assert query == ""

def test_analyze_message_no_sdk():
    """Тестирует, что analyze_message вызывает heuristic, если SDK недоступен."""
    with patch('gemini_init.HAS_GENAI', False):
        with patch('nlp.heuristic', return_value=("chat", "")) as mock_heuristic:
            intent, query = analyze_message(message="нет SDK")
            mock_heuristic.assert_called_once()
            assert intent == "chat"
            assert query == ""

# --- Тесты для _heuristic_fallback (прямой вызов, не нужно мокать generate_smart) ---
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
    intent, query = heuristic(message="ну как там дела в космосе и на земле что нового и интересного происходит")
    assert intent == "search" # Длинное сообщение без ключевых слов считается поиском
    assert query == "ну как там дела в космосе и на земле что нового и интересного происходит"