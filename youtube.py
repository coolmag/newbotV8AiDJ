from __future__ import annotations
import asyncio
import logging
import os
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER: RAILWAY 'OMNIVORE' EDITION (2026)
    Принцип 'Пылесос': берем любой формат (WebM/Opus/M4A) и конвертируем в MP3.
    Решает проблему 'Requested format is not available'.
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # --- COOKIES (Работают, не трогаем) ---
        self.cookies_path = Path("cookies/youtube_railway.txt")
        cookies_content = os.getenv("YT_COOKIES_CONTENT") or os.getenv("COOKIES_CONTENT")
        
        if cookies_content:
            try:
                self.cookies_path.parent.mkdir(exist_ok=True)
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies loaded!")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)
        
        self._url_cache: Dict[str, str] = {}

        # --- КОНФИГУРАЦИЯ ИЗ СОВЕТОВ "АРХИТЕКТОРОВ" ---
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            
            # 1. ФОРМАТ: Самая важная часть.
            # Мы просим: "Дай WebM, или M4A, или Opus, или AAC, или вообще хоть что-то"
            "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio/best",
            
            # 2. ОТКЛЮЧЕНИЕ ПРОВЕРОК (Чтобы не падало заранее)
            "ignore_no_formats_error": True,
            # "check_formats": False, # This option is invalid in yt-dlp, and can cause errors.
            
            # 3. КЛИЕНТЫ: iOS и Android сейчас самые живые
            "extractor_args": {
                "youtube": {
                    "player_client": ["ios", "android", "web"],
                    "player_skip": ["webpage", "configs", "js"],
                }
            },
            
            # 4. КОНВЕРТАЦИЯ В MP3 (Обязательно!)
            # Поскольку мы разрешили качать WebM/Opus, их надо превратить в MP3 для Телеграма
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            
            # Настройки сети для Railway
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True,
            'ignoreerrors': True,
        }
        
        if self.cookies_path.exists():
            self.ydl_opts['cookiefile'] = str(self.cookies_path)

        logger.info("🟢 YouTube 'Omnivore' Engine initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        # Добавляем "audio" для точности, если это не прямой поиск
        if "audio" not in clean_query:
            search_text = f"{clean_query} audio"
        else:
            search_text = clean_query

        cache_key = f"yt_search_omni:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                opts = self.ydl_opts.copy()
                opts['extract_flat'] = True # Быстрый поиск
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    try:
                        return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception as e:
                        logger.error(f"Search Error: {e}")
                        return None

            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=25.0)
            except asyncio.TimeoutError:
                return []
            
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry: continue
                    tid = str(entry.get('id', ''))
                    duration = int(entry.get('duration') or 0)
                    
                    if duration > 0 and (duration < 30 or duration > 1200):
                        continue
                        
                    results.append(TrackInfo(
                        identifier=tid,
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown'),
                        duration=duration,
                        source=Source.YOUTUBE,
                        thumbnail_url=None
                    ))

            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        video_id = str(video_id)
        
        # Кэш ID и файлов
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        for ext in ['.mp3', '.m4a', '.webm']:
            existing = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
            if existing.exists() and existing.stat().st_size > 50000:
                return DownloadResult(success=True, file_path=existing, track_info=track_info)

        url = f"https://www.youtube.com/watch?v={video_id}"

        async with self.semaphore:
            logger.info(f"[YT] Downloading: {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    opts = self.ydl_opts.copy()
                    opts['outtmpl'] = str(self._settings.DOWNLOADS_DIR / f"{video_id}.%(ext)s")
                    
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Download Error {video_id}: {e}")
                    return False

            try:
                # Даем 2 минуты на скачивание и конвертацию
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=120.0)
            except asyncio.TimeoutError:
                return DownloadResult(success=False, error_message="Timeout", track_info=track_info)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Failed", track_info=track_info)

            # Ждем файл. Важно искать MP3, так как FFmpeg должен был отработать
            start_wait = time.time()
            while time.time() - start_wait < 15:
                # Ищем в первую очередь MP3, так как мы просили конвертацию
                mp3_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
                if mp3_path.exists() and mp3_path.stat().st_size > 50000:
                    return DownloadResult(success=True, file_path=mp3_path, track_info=track_info)
                
                # Если конвертация не удалась, но есть исходник - отдаем его
                for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):
                    if path.is_file() and path.stat().st_size > 50000:
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                        
                await asyncio.sleep(1)
            
            return DownloadResult(success=False, error_message="File lost", track_info=track_info)