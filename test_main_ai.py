import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock, call
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

# Мок даунлоадера
@pytest.fixture
def mock_downloader():
    downloader = AsyncMock()
    async def search_side_effect(*args, **kwargs):
        query = kwargs.get("query", "")
        if "Artist1 - Song1" in query:
            return [TrackInfo(identifier="vid1", title="Song1", artist="Artist1", duration=180)]
        if "Artist2 - Song2" in query:
            return [TrackInfo(identifier="vid2", title="Song2", artist="Artist2", duration=200)]
        return []
    downloader.search.side_effect = search_side_effect
    return downloader

# --- ТЕСТЫ ---

@patch('google.genai.Client')
@pytest.mark.asyncio
async def test_ai_dj_generate_success_primary_model(mock_genai_client, client, mock_downloader):
    """
    Тест успешного ответа от основной модели (gemini-1.5-flash).
    """
    # 1. Настройка моков
    ai_response_data = {"intro": "Hi from flash!", "tracks": ["Artist1 - Song1"]}
    mock_response_text = json.dumps(ai_response_data)
    
    mock_genai_instance = MagicMock()
    mock_genai_instance.models.generate_content.return_value = MockGenAIResponse(mock_response_text)
    mock_genai_client.return_value = mock_genai_instance
    
    app.state.downloader = mock_downloader

    # 2. Выполнение
    response = client.get("/api/ai/dj?prompt=test")

    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    assert data["dj_intro"] == "Hi from flash!"
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Song1"
    
    # Проверяем, что была вызвана только первая модель
    mock_genai_instance.models.generate_content.assert_called_once_with(
        model='gemini-1.5-flash',
        contents="""
    Ты — DJ Aurora.
    1. Подбери 5 треков.
    2. Придумай интро (1 фраза).
    JSON: {"intro": "...", "tracks": ["Artist - Title"]}
    """ + "\n\nQuery: test"
    )

@patch('google.genai.Client')
@pytest.mark.asyncio
async def test_ai_dj_generate_fallback_model_success(mock_genai_client, client, mock_downloader):
    """
    Тест цепочки отказоустойчивости: первая модель падает, вторая отвечает успешно.
    """
    # 1. Настройка моков
    ai_response_data = {"intro": "Hi from pro!", "tracks": ["Artist2 - Song2"]}
    mock_response_text = json.dumps(ai_response_data)
    
    mock_genai_instance = MagicMock()
    # Настраиваем side_effect: первая вернет ошибку, вторая - успешный ответ
    mock_genai_instance.models.generate_content.side_effect = [
        Exception("Model not found"),
        MockGenAIResponse(mock_response_text)
    ]
    mock_genai_client.return_value = mock_genai_instance
    
    app.state.downloader = mock_downloader

    # 2. Выполнение
    response = client.get("/api/ai/dj?prompt=test")

    # 3. Проверки
    assert response.status_code == 200
    data = response.json()
    assert data["dj_intro"] == "Hi from pro!"
    assert len(data["playlist"]) == 1
    assert data["playlist"][0]["title"] == "Song2"

    # Проверяем, что были вызваны ОБЕ модели по очереди
    calls = mock_genai_instance.models.generate_content.call_args_list
    assert len(calls) == 2
    # Первая попытка с 'gemini-1.5-flash'
    assert calls[0].kwargs['model'] == 'gemini-1.5-flash'
    # Вторая (успешная) попытка с 'gemini-1.5-pro'
    assert calls[1].kwargs['model'] == 'gemini-1.5-pro'