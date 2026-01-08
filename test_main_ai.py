import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import os
import json
import g4f

from main import app, get_settings, BACKUP_INTROS
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
        MAX_CONCURRENT_DOWNLOADS=3
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
        if "Awesome Band - Great Song" in query:
            return [TrackInfo(identifier="vid1", title="Great Song", artist="Awesome Band", duration=180)]
        if "fallback_prompt" in query:
             return [TrackInfo(identifier="vid_fallback", title="Fallback Song", artist="Fallback Artist", duration=120)]
        return []
    downloader.search.side_effect = search_side_effect
    return downloader

# --- ТЕСТЫ ДЛЯ G4F С BACKUP_INTROS ---

@patch('g4f.ChatCompletion.create_async')
@pytest.mark.asyncio
async def test_ai_dj_g4f_success(mock_create_async, client, mock_downloader):
    """
    Тест: успешный ответ от g4f.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    ai_response_data = {
        "intro": "Провайдер на связи!",
        "tracks": ["Awesome Band - Great Song"]
    }
    mock_create_async.return_value = json.dumps(ai_response_data)

    # 2. Выполнение запроса
    response = client.get("/api/ai/dj?prompt=test prompt")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    assert data["dj_intro"] == "Провайдер на связи!"
    assert len(data["playlist"]) == 1
    mock_downloader.search.assert_called_once_with(query="Awesome Band - Great Song", limit=1)

@patch('g4f.ChatCompletion.create_async')
@pytest.mark.asyncio
async def test_ai_dj_g4f_fails_uses_backup_intro(mock_create_async, client, mock_downloader):
    """
    Тест: g4f не отвечает, система должна использовать случайное интро из BACKUP_INTROS.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    mock_create_async.return_value = "" # Имитируем пустой ответ от AI

    # 2. Выполнение запроса
    response = client.get("/api/ai/dj?prompt=fallback_prompt")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что интро - одна из резервных фраз
    assert data["dj_intro"] in BACKUP_INTROS
    # Проверяем, что в плейлист попал исходный промпт
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Fallback Song"
    mock_downloader.search.assert_called_once_with(query="fallback_prompt", limit=1)
