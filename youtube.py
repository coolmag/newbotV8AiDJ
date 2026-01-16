from __future__ import annotations
import asyncio
import logging
import os
import random
from pathlib import Path
from typing import List, Optional, Dict

import vk_api
from vk_api.audio import VkAudio
import httpx

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER CLASS:
    Внешне выглядит как YouTubeDownloader (для совместимости с radio.py),
    но внутри работает на движке VK Music (Protocol: Kate Mobile).
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Лимиты для ВК мягче, можно качать быстрее
        self.semaphore = asyncio.Semaphore(5) 
        self.search_semaphore = asyncio.Semaphore(10)
        
        self.vk_session = None
        self.vk_audio = None
        self.is_active = False

        self.login = os.getenv("VK_LOGIN")
        self.password = os.getenv("VK_PASSWORD")

        if self.login and self.password:
            self._auth_vk()
        else:
            logger.critical("⛔️ VK_LOGIN or VK_PASSWORD not found! Music will not work.")

    def _auth_vk(self):
        try:
            # Маскируемся под официальный клиент Kate Mobile Android
            # Это дает доступ к аудио API без капчи (чаще всего)
            self.vk_session = vk_api.VkApi(
                login=self.login, 
                password=self.password,
                app_id=2685278  # ID приложения Kate Mobile
            )
            self.vk_session.auth()
            self.vk_audio = VkAudio(self.vk_session)
            self.is_active = True
            logger.info("✅ VK Music Engine: ONLINE (Kate Mobile Protocol)")
        except vk_api.AuthError as e:
            logger.error(f"❌ VK Auth Error: {e}")
        except Exception as e:
            logger.error(f"❌ VK Init Error: {e}")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        """
        Поиск музыки ВКонтакте.
        """
        if not self.is_active:
            logger.warning("VK not active, returning empty search.")
            return []

        # Кэширование запросов
        clean_query = query.lower().strip()
        cache_key = f"vk_search_v1:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                try:
                    # vk_audio.search возвращает итератор, превращаем в список
                    # per_page - сколько грузить за раз
                    return list(self.vk_audio.search(query, count=limit))
                except Exception as e:
                    logger.error(f"VK Search API Error: {e}")
                    # Если сессия протухла, можно попробовать перелогиниться (простая реализация)
                    return []

            raw_tracks = await loop.run_in_executor(None, do_search)
            
            results = []
            for t in raw_tracks:
                # В ВК ID состоит из owner_id и audio_id
                track_id = f"{t['owner_id']}_{t['id']}"
                title = t.get('title', 'Unknown')
                artist = t.get('artist', 'Unknown')
                duration = t.get('duration', 0)
                url = t.get('url', '') # Прямая ссылка на mp3 (действует ограниченное время)
                
                # Пропускаем слишком короткие (интро) или слишком длинные (миксы)
                if duration < 30 or duration > 1800: 
                    continue
                
                # Мы временно сохраняем URL в поле thumbnail_url (хак для передачи данных)
                # Или просто полагаемся на то, что download снова получит ссылку
                
                info = TrackInfo(
                    identifier=track_id,
                    title=title,
                    artist=artist,
                    duration=duration,
                    source=Source.YOUTUBE, # Оставляем тип YOUTUBE для совместимости с моделями
                    thumbnail_url=None
                )
                results.append(info)

            # Сохраняем в кэш
            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            
            return results

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        """
        Получение инфо о треке по ID (owner_id_audio_id).
        """
        # В этой архитектуре мы обычно уже имеем инфо из поиска.
        # Но если нужно получить отдельно, это сложно без прямого поиска.
        # Возвращаем заглушку, так как radio.py передает track_info.
        return None

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """
        Скачивание трека из ВК.
        """
        if not self.is_active:
            return DownloadResult(success=False, error_message="VK Auth Failed")

        # 1. Проверяем, есть ли уже file_id в кэше Телеграма
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id:
            logger.info(f"[VK] Cache HIT (Telegram ID) for {video_id}")
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        # 2. Проверяем файл на диске
        existing_path = self._find_downloaded_file(video_id)
        if existing_path:
            logger.info(f"[VK] Cache HIT (File) for {video_id}")
            return DownloadResult(success=True, file_path=existing_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"[VK] Downloading: {video_id}")
            
            try:
                owner_id, audio_id = map(int, video_id.split('_'))
                
                # --- ПОЛУЧЕНИЕ ССЫЛКИ ---
                # Нам нужно получить свежую ссылку на mp3, так как ссылки из поиска протухают
                loop = asyncio.get_running_loop()
                def get_fresh_url():
                    # vk_audio.get_audio_by_id возвращает dict или None
                    try:
                        # Этот метод парсит страницу, это надежно
                        return self.vk_audio.get_audio_by_id(owner_id, audio_id).get('url')
                    except Exception as e:
                        logger.error(f"VK Get URL Error: {e}")
                        return None
                
                mp3_url = await loop.run_in_executor(None, get_fresh_url)
                
                if not mp3_url:
                    # Попытка №2: иногда audio_by_id не находит, пробуем поиск по ID
                    # Это сложнее, пропустим для простоты
                    return DownloadResult(success=False, error_message="VK Link parsing failed", track_info=track_info)

                # --- СКАЧИВАНИЕ ---
                file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
                
                async with httpx.AsyncClient() as client:
                    # Скачиваем потоком
                    async with client.stream('GET', mp3_url) as response:
                        if response.status_code != 200:
                            return DownloadResult(success=False, error_message=f"HTTP {response.status_code}", track_info=track_info)
                        
                        with open(file_path, "wb") as f:
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)

                if file_path.exists() and file_path.stat().st_size > 10000:
                    logger.info(f"[VK] Download Success: {file_path}")
                    return DownloadResult(success=True, file_path=file_path, track_info=track_info)
                else:
                    return DownloadResult(success=False, error_message="File empty or small", track_info=track_info)

            except Exception as e:
                logger.error(f"[VK] Critical Download Error: {e}")
                return DownloadResult(success=False, error_message=str(e), track_info=track_info)

    # === ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ (Для совместимости с radio.py) ===
    
    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        exact_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if exact_path.exists() and exact_path.stat().st_size > 10240: # > 10KB
            return exact_path
        return None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        return self._find_downloaded_file(video_id)

    async def get_random_cached_tracks(self, limit: int = 10) -> List[TrackInfo]:
        """Возвращает рандомные треки из папки downloads"""
        loop = asyncio.get_running_loop()
        def scan_files():
            return list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))
        
        files = await loop.run_in_executor(None, scan_files)
        if not files: return []
        random.shuffle(files)
        
        tracks = []
        for f in files[:limit]:
            # Пытаемся сделать "фейковый" track info из имени файла
            # Имя файла: owner_id_audio_id.mp3
            vid = f.stem
            tracks.append(TrackInfo(identifier=vid, title="Cached Track", artist="VK Archive", duration=0))
        return tracks