import pytest
from unittest.mock import Mock, patch

# Импортируем функцию и типы, которые нужно мокать
from nlp import analyze_message
try:
    from google import genai
    from google.genai import types
    GENAI_INSTALLED = True
except ImportError:
    GENAI_INSTALLED = False

# Пропускаем все тесты в этом файле, если SDK не установлен
pytestmark = pytest.mark.skipif(not GENAI_INSTALLED, reason="google-genai SDK not installed")

def test_analyze_message_success():
    """Тестирует happy-path с моком клиента и его методов."""
    # Мокаем ответ от API
    mock_response = Mock()
    mock_response.text = '{"intent": "radio", "query": "энергичные русские хиты 2025"}'
    
    # Мокаем сам клиент
    mock_client = Mock(spec=genai.Client)
    # Мокаем цепочку вызовов client.models.generate_content
    mock_client.models.generate_content.return_value = mock_response

    # Вызываем нашу функцию с мок-клиентом
    intent, query = analyze_message("давай давай", mock_client)
    
    # Проверяем, что был вызван правильный метод
    mock_client.models.generate_content.assert_called_once()
    
    # Проверяем результат
    assert intent == "radio"
    assert query == "энергичные русские хиты 2025"

def test_analyze_message_fallback_on_no_client():
    """Тестирует fallback, если клиент None."""
    intent, query = analyze_message("тест", None)
    assert intent == "search"
    assert query == "тест"

def test_analyze_message_fallback_on_api_error():
    """Тестирует fallback при ошибке вызова API."""
    mock_client = Mock(spec=genai.Client)
    mock_client.models.generate_content.side_effect = Exception("API is down")

    intent, query = analyze_message("ошибка", mock_client)

    assert intent == "search"
    assert query == "ошибка"