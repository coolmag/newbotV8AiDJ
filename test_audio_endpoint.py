import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
import os

from main import app, get_settings
from models import DownloadResult

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

# --- ТЕСТЫ ДЛЯ /audio/{video_id}.mp3 ---

@pytest.mark.asyncio
async def test_get_audio_file_exists(client):
    """
    Тест: файл уже существует и отдается сразу.
    """
    video_id = "existing_video"
    fake_file_path = Path("test_downloads") / f"{video_id}.mp3"
    
    # Мокаем downloader и его методы
    mock_downloader = MagicMock()
    mock_downloader._find_downloaded_file.return_value = fake_file_path
    app.state.downloader = mock_downloader
    
    # Мокаем os.path.exists и path.stat для FileResponse
    with patch('os.path.exists', return_value=True), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        mock_stat.return_value.st_size = 2048 # Размер больше 1024

        response = client.get(f"/audio/{video_id}.mp3")
        
        assert response.status_code == 200
        assert response.headers['media-type'] == "audio/mpeg"
        
        # Проверяем, что download не был вызван
        mock_downloader.download.assert_not_called()

@pytest.mark.asyncio
async def test_get_audio_file_downloads_successfully(client):
    """
    Тест: файл не существует, запускается загрузка и завершается успешно.
    """
    video_id = "new_video"
    fake_file_path = Path("test_downloads") / f"{video_id}.mp3"

    # Мокаем downloader
    mock_downloader = AsyncMock()
    mock_downloader._find_downloaded_file.return_value = None # Файла нет
    # Мокаем успешный результат скачивания
    mock_downloader.download.return_value = DownloadResult(success=True, file_path=fake_file_path)
    app.state.downloader = mock_downloader

    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        mock_stat.return_value.st_size = 2048

        response = client.get(f"/audio/{video_id}.mp3")
        
        assert response.status_code == 200
        assert response.headers['media-type'] == "audio/mpeg"
        
        # Проверяем, что download был вызван
        mock_downloader.download.assert_called_once_with(video_id)

@pytest.mark.asyncio
async def test_get_audio_file_download_fails(client):
    """
    Тест: файл не существует, загрузка падает.
    """
    video_id = "failed_video"

    # Мокаем downloader
    mock_downloader = AsyncMock()
    mock_downloader._find_downloaded_file.return_value = None # Файла нет
    # Мокаем провальный результат скачивания
    mock_downloader.download.return_value = DownloadResult(success=False)
    app.state.downloader = mock_downloader

    response = client.get(f"/audio/{video_id}.mp3")
    
    assert response.status_code == 404
    assert response.json() == {"error": "Download failed"}
    
    # Проверяем, что download был вызван
    mock_downloader.download.assert_called_once_with(video_id)

