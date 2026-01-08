import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import os
import json

from main import app, get_settings
from models import TrackInfo

# Фикстура для FastAPI TestClient
@pytest.fixture
def client():
    app.dependency_overrides[get_settings] = lambda: MagicMock(
        BOT_TOKEN="test_token",
        WEBHOOK_URL="test_url",
        DOWNLOADS_DIR="test_downloads",
        TEMP_AUDIO_DIR="test_temp",
        CACHE_DB_PATH="test_cache.db",
        PROXY_URL=None,
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
        if "Synth Riders - Power" in query:
            return [TrackInfo(identifier="vid1", title="Power", artist="Synth Riders", duration=180)]
        if "fallback_query" in query:
            return [TrackInfo(identifier="vid_fallback", title="Fallback Song", artist="Fallback Artist", duration=120)]
        return []
    downloader.search.side_effect = search_side_effect
    return downloader

# --- ТЕСТЫ ДЛЯ НОВОЙ АРХИТЕКТУРЫ G4F ---

@patch('main.sync_g4f_request')
@pytest.mark.asyncio
async def test_ai_dj_g4f_success(mock_sync_g4f, client, mock_downloader):
    """
    Тест: успешный ответ от sync_g4f_request.
    Проверяет, что основная логика работает, JSON парсится, и треки ищутся.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    
    ai_response_data = {
        "intro": "Поехали!",
        "tracks": ["Synth Riders - Power"]
    }
    # Имитируем ответ от sync_g4f_request: (json_string, model_name)
    mock_sync_g4f.return_value = (json.dumps(ai_response_data), "g4f.models.gpt_4o")

    # 2. Выполнение запроса
    response = client.get("/api/ai/dj?prompt=synthwave")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    mock_sync_g4f.assert_called_once_with("synthwave")
    
    assert data["dj_intro"] == "Поехали!"
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Power"
    
    mock_downloader.search.assert_called_once_with(query="Synth Riders - Power", limit=1)

@patch('main.sync_g4f_request')
@pytest.mark.asyncio
async def test_ai_dj_g4f_fails_fallback_to_search(mock_sync_g4f, client, mock_downloader):
    """
    Тест: sync_g4f_request выбрасывает исключение.
    Проверяет, что система корректно переходит к резервному поиску.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    mock_sync_g4f.side_effect = Exception("All models failed")

    # 2. Выполнение запроса
    prompt_for_fallback = "fallback_query"
    response = client.get(f"/api/ai/dj?prompt={prompt_for_fallback}")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    mock_sync_g4f.assert_called_once_with(prompt_for_fallback)
    
    assert data["dj_intro"] == "Сбой нейросети. Запускаю резерв."
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Fallback Song"

    # Проверяем, что был вызван резервный поиск
    mock_downloader.search.assert_called_once_with(query=prompt_for_fallback, limit=10)