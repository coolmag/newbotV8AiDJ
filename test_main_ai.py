import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import os
import json

# Убираем зависимость от ключа Google, если он был
if "GEMINI_API_KEY" in os.environ:
    del os.environ["GEMINI_API_KEY"]

from main import app, get_settings
from models import TrackInfo

# Фикстура для FastAPI TestClient
@pytest.fixture
def client():
    # Мокаем настройки, чтобы не зависеть от .env файла
    app.dependency_overrides[get_settings] = lambda: MagicMock(
        BOT_TOKEN="test_token",
        WEBHOOK_URL="test_url",
        DOWNLOADS_DIR="test_downloads",
        TEMP_AUDIO_DIR="test_temp",
        CACHE_DB_PATH="test_cache.db",
        PROXY_URL=None,
        MAX_CONCURRENT_DOWNLOADS=3 # Добавим недостающие атрибуты
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}

# Фикстура для мока YouTubeDownloader
@pytest.fixture
def mock_downloader():
    downloader = AsyncMock()
    async def search_side_effect(*args, **kwargs):
        query = kwargs.get("query", "")
        if "Epic Rock - Victory" in query:
            return [TrackInfo(identifier="vid1", title="Victory", artist="Epic Rock", duration=180)]
        if "fallback_query" in query:
            return [TrackInfo(identifier="vid_fallback", title="Fallback Song", artist="Fallback Artist", duration=120)]
        return []
    downloader.search.side_effect = search_side_effect
    return downloader

# --- ТЕСТЫ ДЛЯ G4F СО СТРОКОВЫМИ МОДЕЛЯМИ ---

@patch('main.sync_ask_ai')
@pytest.mark.asyncio
async def test_ai_dj_g4f_success(mock_sync_ask_ai, client, mock_downloader):
    """
    Тест: успешный ответ от sync_ask_ai.
    Проверяет, что основная логика работает, JSON парсится, и треки ищутся.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    
    ai_response_data = {
        "intro": "Врубаю эпичный рок!",
        "tracks": ["Epic Rock - Victory"]
    }
    # Имитируем ответ от sync_ask_ai: (json_string)
    mock_sync_ask_ai.return_value = json.dumps(ai_response_data)

    # 2. Выполнение запроса
    response = client.get("/api/ai/dj?prompt=epic rock")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    mock_sync_ask_ai.assert_called_once_with("epic rock")
    
    assert data["dj_intro"] == "Врубаю эпичный рок!"
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Victory"
    
    # Проверяем, что поиск был вызван для трека из ответа AI
    mock_downloader.search.assert_called_once_with(query="Epic Rock - Victory", limit=1)

@patch('main.sync_ask_ai')
@pytest.mark.asyncio
async def test_ai_dj_g4f_returns_none_fallback(mock_sync_ask_ai, client, mock_downloader):
    """
    Тест: sync_ask_ai вернула None (все модели g4f не ответили).
    Проверяет, что система корректно переходит к резервному поиску.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    mock_sync_ask_ai.return_value = None

    # 2. Выполнение запроса
    prompt_for_fallback = "fallback_query"
    response = client.get(f"/api/ai/dj?prompt={prompt_for_fallback}")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    mock_sync_ask_ai.assert_called_once_with(prompt_for_fallback)
    
    # Проверяем, что используется интро для сбоя и резервный плейлист
    assert data["dj_intro"] == "Сбой нейросети. Резервный канал."
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Fallback Song"

    # Проверяем, что был вызван резервный поиск
    mock_downloader.search.assert_called_once_with(query=prompt_for_fallback, limit=10)
