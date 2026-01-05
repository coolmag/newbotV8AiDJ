import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.error import Forbidden
from radio import RadioSession, TrackInfo

 @pytest.mark.asyncio
async def test_radio_stops_on_forbidden(test_settings):
    """
    Проверяет, что RadioSession останавливается, если бот заблокирован (Forbidden).
    """
    # 1. Setup Mock Bot
    mock_bot = AsyncMock()
    # Имитируем Forbidden при попытке отправить статус
    mock_bot.send_message.side_effect = Forbidden("Forbidden: bot was blocked by the user")

    # 2. Setup Mock Downloader
    mock_downloader = AsyncMock()
    # Возвращаем фейковый трек, чтобы цикл попытался его "сыграть"
    fake_track = TrackInfo(identifier="123", title="Test", artist="Art", duration=100)
    mock_downloader.search.return_value = [fake_track] 
    mock_downloader.download.return_value = MagicMock(success=True, file_id="file123", file_path=None)

    # 3. Create Session
    session = RadioSession(
        chat_id=12345,
        bot=mock_bot,
        downloader=mock_downloader,
        settings=test_settings,
        query="test"
    )

    # 4. Start session directly (call internal loop logic or just check _update_status)
    session.is_running = True
    
    # Вызываем _update_status, который должен поймать Forbidden и остановить сессию
    await session._update_status("Test status")

    # 5. Assertions
    assert session.is_running is False, "Сессия должна была остановиться после Forbidden"
    assert session.status_message is None