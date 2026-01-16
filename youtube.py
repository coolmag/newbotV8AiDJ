from __future__ import annotations
import asyncio
import logging
import os
import random
import time
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
    VK Music Engine (Adapter Pattern)
    Внешне совместим с YouTubeDownloader, внутри - VK API.
    """
    
    # Rate limiting настройки
    MIN_DELAY = 1.5  # Минимальная задержка между запросами (секунды)
    MAX_DELAY = 4.0  # Максимальная задержка
    MAX_RETRIES = 3  # Максимум попыток при ошибках
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Semaphores для контроля нагрузки
        self.semaphore = asyncio.Semaphore(3)  # 3 одновременных скачивания
        self.search_semaphore = asyncio.Semaphore(5)  # 5 одновременных поисков
        
        # Rate limiting
        self._last_request_time = 0
        self._request_lock = asyncio.Lock()
        
        self.vk_session = None
        self.vk_audio = None
        self.is_active = False

        self.login = os.getenv("VK_LOGIN")
        self.password = os.getenv("VK_PASSWORD")

        if self.login and self.password:
            self._auth_vk()
        else:
            logger.critical("⛔️ VK_LOGIN or VK_PASSWORD not found!")

    def _auth_vk(self):
        """Авторизация с защитой от частых попыток."""
        try:
            logger.info("🔐 Попытка VK авторизации...")
            
            # Kate Mobile эмуляция - наиболее стабильный метод
            self.vk_session = vk_api.VkApi(
                login=self.login, 
                password=self.password,
                app_id=2685278,  # Kate Mobile Android
                auth_handler=self._auth_handler,
                captcha_handler=self._captcha_handler
            )
            
            self.vk_session.auth()
            self.vk_audio = VkAudio(self.vk_session)
            self.is_active = True
            logger.info("✅ VK Music Engine: ONLINE (Kate Mobile Protocol)")
            
        except vk_api.AuthError as e:
            logger.error(f"❌ VK Auth Error: {e}")
            self.is_active = False
        except Exception as e:
            logger.error(f"❌ VK Init Error: {e}")
            self.is_active = False

    def _auth_handler(self, phone_or_login, hint, recall, is_reset=False):
        """Обработчик 2FA если есть."""
        # Возвращаем код для подтверждения
        return None  # Нужно ввести код вручную, если есть 2FA

    def _captcha_handler(self, captcha):
        """Обработчик капчи - пропускаем (не автоматизируем)."""
        logger.warning("⚠️ Капча получена, пропускаем...")
        return None

    async def _rate_limited_request(self):
        """Защита от Too Many Requests."""
        async with self._request_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            
            if elapsed < self.MIN_DELAY:
                sleep_time = self.MIN_DELAY - elapsed + random.uniform(0, 1)
                await asyncio.sleep(sleep_time)
            
            self._last_request_time = time.time()

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        """Поиск с rate limiting и кэшированием."""
        if not self.is_active:
            logger.warning("VK not active")
            return []

        # Проверяем кэш
        clean_query = query.lower().strip()
        cache_key = f"vk_search:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached:
            logger.debug(f"[VK] Cache HIT for: {clean_query}")
            return cached

        async with self.search_semaphore:
            await self._rate_limited_request()
            
            for attempt in range(self.MAX_RETRIES):
                try:
                    loop = asyncio.get_running_loop()
                    
                    def do_search():
                        try:
                            return list(self.vk_audio.search(query, count=limit))
                        except Exception as e:
                            logger.warning(f"VK search error: {e}")
                            return []

                    raw_tracks = await loop.run_in_executor(None, do_search)
                    
                    if not raw_tracks:
                        if attempt < self.MAX_RETRIES - 1:
                            delay = (2 ** attempt) + random.uniform(0, 1)
                            logger.info(f"[VK] Retry in {delay:.1f}s...")
                            await asyncio.sleep(delay)
                            continue
                        return []

                    break  # Успешно получили данные
                    
                except Exception as e:
                    logger.error(f"[VK] Search attempt {attempt+1} failed: {e}")
                    if attempt >= self.MAX_RETRIES - 1:
                        return []

            # Парсинг результатов
            results = []
            for t in raw_tracks:
                track_id = f"{t['owner_id']}_{t['id']}"
                duration = t.get('duration', 0)
                
                # Фильтруем по длительности
                if duration < 30 or duration > 1800:
                    continue
                
                info = TrackInfo(
                    identifier=track_id,
                    title=t.get('title', 'Unknown'),
                    artist=t.get('artist', 'Unknown'),
                    duration=duration,
                    source=Source.YOUTUBE,
                    thumbnail_url=None
                )
                results.append(info)

            # Кэшируем результат (1 час TTL)
            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            
            logger.info(f"[VK] Search '{query}': {len(results)} tracks")
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """Скачивание с кэшированием file_id."""
        if not self.is_active:
            return DownloadResult(success=False, error_message="VK Auth Failed")

        # Проверяем Telegram file_id кэш
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id:
            logger.info(f"[VK] Cache HIT (Telegram ID) for {video_id}")
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        # Проверяем локальный файл
        existing_path = self._find_downloaded_file(video_id)
        if existing_path:
            logger.info(f"[VK] Cache HIT (File) for {video_id}")
            return DownloadResult(success=True, file_path=existing_path, track_info=track_info)

        async with self.semaphore:
            await self._rate_limited_request()
            
            try:
                owner_id, audio_id = map(int, video_id.split('_'))
                
                loop = asyncio.get_running_loop()
                
                def get_fresh_url():
                    try:
                        return self.vk_audio.get_audio_by_id(owner_id, audio_id).get('url')
                    except Exception as e:
                        logger.warning(f"VK get URL error: {e}")
                        return None
                
                mp3_url = await loop.run_in_executor(None, get_fresh_url)
                
                if not mp3_url:
                    return DownloadResult(success=False, error_message="VK Link failed", track_info=track_info)

                # Скачиваем
                file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream('GET', mp3_url) as response:
                        if response.status_code != 200:
                            return DownloadResult(success=False, error_message=f"HTTP {response.status_code}", track_info=track_info)
                        
                        with open(file_path, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                f.write(chunk)

                if file_path.exists() and file_path.stat().st_size > 10000:
                    logger.info(f"[VK] Download OK: {video_id}")
                    return DownloadResult(success=True, file_path=file_path, track_info=track_info)
                else:
                    return DownloadResult(success=False, error_message="File too small", track_info=track_info)

            except Exception as e:
                logger.error(f"[VK] Download error: {e}")
                return DownloadResult(success=False, error_message=str(e), track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        """Кэшируем Telegram file_id для повторного использования."""
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        exact_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if exact_path.exists() and exact_path.stat().st_size > 10240:
            return exact_path
        return None

    async def get_random_cached_tracks(self, limit: int = 10) -> List[TrackInfo]:
        """Возвращает рандомные треки из кэша."""
        loop = asyncio.get_running_loop()
        def scan_files():
            return list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))
        
        files = await loop.run_in_executor(None, scan_files)
        if not files:
            return []
        
        random.shuffle(files)
        tracks = []
        
        for f in files[:limit]:
            vid = f.stem
            tracks.append(TrackInfo(identifier=vid, title="Cached Track", artist="VK Archive", duration=0))
        
        return tracks