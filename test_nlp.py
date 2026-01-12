import pytest
from unittest.mock import AsyncMock, patch
import google.genai as genai

from nlp import analyze_message

# Поскольку мы больше не используем Settings, можно убрать этот импорт

@pytest.mark.asyncio
async def test_analyze_message_with_client():
    """Тестирует happy-path с новым SDK и клиентом."""
    # Создаем мок клиента и модели
    mock_client = AsyncMock(spec=genai.Client)
    mock_model = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = '{"intent": "radio", "query": "new rock mix"}'
    
    # Настраиваем цепочку вызовов
    mock_client.get_model.return_value = mock_model
    mock_model.generate_content_async.return_value = mock_response

    # Вызываем нашу функцию
    intent, query = await analyze_message("включи новый рок", mock_client)

    # Проверяем результат
    assert intent == "radio"
    assert query == "new rock mix"
    mock_client.get_model.assert_called_once_with("gemini-3-flash-preview")
    mock_model.generate_content_async.assert_called_once()

@pytest.mark.asyncio
async def test_analyze_message_no_client():
    """Тестирует fallback, если клиент не был инициализирован."""
    intent, query = await analyze_message("любой запрос", None)
    
    assert intent == "search"
    assert query == "любой запрос"

@pytest.mark.asyncio
async def test_analyze_message_api_error():
    """Тестирует fallback при ошибке генерации контента."""
    mock_client = AsyncMock(spec=genai.Client)
    mock_model = AsyncMock()
    mock_model.generate_content_async.side_effect = Exception("Google API is down")
    mock_client.get_model.return_value = mock_model

    intent, query = await analyze_message("запрос с ошибкой", mock_client)
    
    assert intent == "search"
    assert query == "запрос с ошибкой"

@pytest.mark.asyncio
async def test_analyze_message_bad_json_response():
    """Тестирует fallback, если AI вернул некорректный JSON."""
    mock_client = AsyncMock(spec=genai.Client)
    mock_model = AsyncMock()
    mock_response = AsyncMock()
    mock_response.text = 'это не json'
    mock_client.get_model.return_value = mock_model
    mock_model.generate_content_async.return_value = mock_response

    intent, query = await analyze_message("запрос с плохим json", mock_client)

    assert intent == "search"
    assert query == "запрос с плохим json"