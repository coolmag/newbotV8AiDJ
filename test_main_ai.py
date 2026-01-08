import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import os
import json
import g4f

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
        return []
    downloader.search.side_effect = search_side_effect
    return downloader

# --- ТЕСТЫ ДЛЯ G4F LEGACY (v0.3.x) С ПРОВАЙДЕРАМИ ---

@patch('g4f.ChatCompletion.create_async')
@pytest.mark.asyncio
async def test_ai_dj_provider_fallback_success(mock_create_async, client, mock_downloader):
    """
    Тест: первый провайдер g4f падает, второй отвечает успешно.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    
    ai_response_data = {
        "intro": "Второй провайдер на связи!",
        "tracks": ["Awesome Band - Great Song"]
    }
    # Имитируем падение первого вызова и успешный второй
    mock_create_async.side_effect = [
        Exception("Provider 1 failed"),
        json.dumps(ai_response_data)
    ]

    # 2. Выполнение запроса
    response = client.get("/api/ai/dj?prompt=test prompt")
    
    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что были вызваны 2 провайдера
    assert mock_create_async.call_count == 2
    
    # Проверяем, что интро от второго, успешного провайдера
    assert data["dj_intro"] == "Второй провайдер на связи!"
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["artist"] == "Awesome Band"
    
    # Проверяем, что downloader был вызван для трека из ответа AI
    mock_downloader.search.assert_called_once_with(query="Awesome Band - Great Song", limit=1)

@patch('g4f.ChatCompletion.create_async')
@pytest.mark.asyncio
async def test_ai_dj_all_providers_fail(mock_create_async, client, mock_downloader):
    """
    Тест: все провайдеры g4f падают.
    Система должна вернуть стандартный ответ об ошибке.
    """
    # 1. Настройка моков
    app.state.downloader = mock_downloader
    # Все вызовы будут возвращать ошибку
    mock_create_async.side_effect = Exception("Provider failed")

    # 2. Выполнение запроса
    response = client.get("/api/ai/dj?prompt=some_prompt")
    
    # 3. Проверки
    from main import PROVIDERS # импортируем, чтобы знать, сколько раз должен быть вызов
    assert mock_create_async.call_count == len(PROVIDERS)
    
    data = response.json()
    # Проверяем, что вернулся жестко заданный в коде JSON-ответ об ошибке
    assert data["intro"] == "Связь нестабильна. Включаю музыку."
    assert len(data["playlist"]) == 0
    
    # Убедимся, что после этого основной поиск не был вызван, т.к. AI вернул пустой плейлист
    mock_downloader.search.assert_not_called()