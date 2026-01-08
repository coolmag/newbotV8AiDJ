import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import os
import json

# Убираем зависимость от ключа Google
if "GEMINI_API_KEY" in os.environ:
    del os.environ["GEMINI_API_KEY"]

from main import app, get_settings
from models import TrackInfo

@pytest.fixture
def client():
    # Переопределяем зависимости для тестов
    app.dependency_overrides[get_settings] = lambda: MagicMock(
        MAX_CONCURRENT_DOWNLOADS=3,
        DOWNLOADS_DIR="test_downloads"
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}

@pytest.fixture
def mock_downloader():
    downloader = AsyncMock()
    async def search_side_effect(*args, **kwargs):
        query = kwargs.get("query", "")
        if "Cool Artist - Awesome Song" in query:
            return [TrackInfo(identifier="vid1", title="Awesome Song", artist="Cool Artist", duration=180)]
        return []
    downloader.search.side_effect = search_side_effect
    return downloader

# --- ТЕСТ ДЛЯ G4F ---

@patch('g4f.ChatCompletion.create')
@pytest.mark.asyncio
async def test_ai_dj_generate_g4f_success(mock_g4f_create, client, mock_downloader):
    """
    Тест успешного ответа от нового AI-провайдера g4f.
    """
    # 1. Настройка моков
    ai_response_data = {
        "intro": "Here are some sick beats!",
        "tracks": ["Cool Artist - Awesome Song"]
    }
    # g4f возвращает строку, иногда с мусором, поэтому имитируем это
    mock_response_text = f"Here is the JSON you requested: ```json
{json.dumps(ai_response_data)}
```"
    mock_g4f_create.return_value = mock_response_text
    
    app.state.downloader = mock_downloader

    # 2. Выполнение
    prompt = "phonk"
    response = client.get(f"/api/ai/dj?prompt={prompt}")

    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что интро и плейлист из ответа AI
    assert data["dj_intro"] == ai_response_data["intro"]
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Awesome Song"
    
    # Проверяем, что g4f был вызван с правильными параметрами
    mock_g4f_create.assert_called_once()
    args, kwargs = mock_g4f_create.call_args
    assert kwargs['model'] == "gpt-3.5-turbo"
    assert any(msg['role'] == 'user' and prompt in msg['content'] for msg in kwargs['messages'])

    # Проверяем, что downloader был вызван для трека из ответа AI
    mock_downloader.search.assert_called_once_with(query="Cool Artist - Awesome Song", limit=1)
