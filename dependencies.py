from functools import lru_cache
from typing import Optional

from telegram import Bot

from config import Settings, get_settings
from cache_service import CacheService
from youtube import YouTubeDownloader

# Синглтоны
_cache_service: Optional[CacheService] = None
_downloader: Optional[YouTubeDownloader] = None
_radio_manager = None  # Тип будет RadioManager, но импортируем лениво
_bot: Optional[Bot] = None


def get_settings_dep() -> Settings:
    return get_settings()


def get_cache_service_dep() -> CacheService:
    global _cache_service
    if _cache_service is None:
        settings = get_settings_dep()
        _cache_service = CacheService(settings.CACHE_DB_PATH)
    return _cache_service


def get_downloader_dep() -> YouTubeDownloader:
    global _downloader
    if _downloader is None:
        settings = get_settings_dep()
        cache = get_cache_service_dep()
        _downloader = YouTubeDownloader(settings, cache)
    return _downloader


def get_bot_dep(token: Optional[str] = None) -> Bot:
    global _bot
    if _bot is None:
        if token is None:
            settings = get_settings_dep()
            token = settings.BOT_TOKEN
        _bot = Bot(token=token)
    return _bot


def get_radio_manager_dep():
    """Ленивый импорт RadioManager чтобы избежать циклических зависимостей"""
    global _radio_manager
    if _radio_manager is None:
        from radio import RadioManager
        settings = get_settings_dep()
        bot = get_bot_dep()
        downloader = get_downloader_dep()
        _radio_manager = RadioManager(bot, settings, downloader)
    return _radio_manager


def reset_dependencies():
    """Сброс зависимостей (для тестов)"""
    global _cache_service, _downloader, _radio_manager, _bot
    _cache_service = None
    _downloader = None
    _radio_manager = None
    _bot = None