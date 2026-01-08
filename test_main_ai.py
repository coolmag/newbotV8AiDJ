import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import os
import json

# Устанавливаем фейковый ключ до импорта приложения
os.environ["GEMINI_API_KEY"] = "test-key"

from main import app, get_settings
from models import TrackInfo

# Фикстура для клиента API
@pytest.fixture
def client():
    # Переопределяем зависимости для тестов
    app.dependency_overrides[get_settings] = lambda: MagicMock(
        MAX_CONCURRENT_DOWNLOADS=3,
        DOWNLOADS_DIR="test_downloads"
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {} # Очищаем после теста

# Модель ответа от generate_content
class MockGenAIResponse:
    def __init__(self, text):
        self._text = text

    @property
    def text(self):
        return self._text

# Успешный сценарий: AI вернул JSON, и треки нашлись
@patch('google.genai.Client')
@pytest.mark.asyncio
async def test_ai_dj_generate_success(mock_genai_client, client):
    # 1. Настройка моков
    
    # Мок ответа AI
    ai_response_data = {
        "intro": "Вот крутой микс для вас!",
        "tracks": ["Artist1 - Song1", "Artist2 - Song2"]
    }
    mock_response_text = f"```json\n{json.dumps(ai_response_data)}\n```"
    
    # Мок клиента genai
    mock_genai_instance = MagicMock()
    mock_genai_instance.models.generate_content.return_value = MockGenAIResponse(mock_response_text)
    mock_genai_client.return_value = mock_genai_instance

    # Мок даунлоадера
    mock_downloader = AsyncMock()
    # Настраиваем, чтобы поиск возвращал результат
    async def search_side_effect(*args, **kwargs):
        query = kwargs.get("query", "")
        if "Artist1 - Song1" in query:
            return [TrackInfo(identifier="vid1", title="Song1", artist="Artist1", duration=180)]
        if "Artist2 - Song2" in query:
            return [TrackInfo(identifier="vid2", title="Song2", artist="Artist2", duration=200)]
        return []

    mock_downloader.search = AsyncMock(side_effect=search_side_effect)
    app.state.downloader = mock_downloader

    # 2. Выполнение запроса
    prompt = "synthwave mix"
    response = client.get(f"/api/ai/dj?prompt={prompt}")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что интро из ответа AI
    assert data["dj_intro"] == ai_response_data["intro"]
    
    # Проверяем, что плейлист содержит треки, найденные даунлоадером
    assert len(data["playlist"]) == 2
    assert data["playlist"][0]["title"] == "Song1"
    assert data["playlist"][1]["title"] == "Song2"

    # Проверяем, что AI был вызван с правильным промптом
    mock_genai_instance.models.generate_content.assert_called_once()
    call_args = mock_genai_instance.models.generate_content.call_args
    assert prompt in call_args.kwargs['contents']
    
    # Проверяем, что downloader.search был вызван для каждого трека из ответа AI
    assert mock_downloader.search.call_count == 2
    mock_downloader.search.assert_any_call(query="Artist1 - Song1", limit=1)
    mock_downloader.search.assert_any_call(query="Artist2 - Song2", limit=1)

