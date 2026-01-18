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
    ADAPTER: RAILWAY 'DUAL-CONFIG' EDITION (2026)
    - Раздельные конфиги для поиска и скачивания.
    - Принудительный generic extractor для обхода бана скачивания.
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # --- COOKIES ---
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
        
        # --- ОПЦИИ ДЛЯ ПОИСКА (Работают, минимум изменений) ---
        self.search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 20,
            "retries": 3,
            "extractor_args": {
                "youtube": {
                    "player_client": ["ios", "web"],
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        }

        # --- ОПЦИИ ДЛЯ СКАЧИВАНИЯ (Агрессивные, с fallback) ---
        self.download_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best[height<=480]/best",
            
            # --- ГЛАВНЫЙ ФИКС 2026 ---
            # Заставляем yt-dlp использовать универсальный экстрактор, а не специализированный под YouTube,
            # что обходит ошибку "No video formats found" при невалидных для скачивания куках.
            "force_generic_extractor": True,
            
            "ignore_no_formats_error": True,
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "socket_timeout": 45,
            "retries": 10,
            "fragment_retries": 10,
            'nocheckcertificate': True,
        }
        
        # Применяем куки к обоим конфигам, если они есть
        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            self.download_opts['cookiefile'] = str(self.cookies_path)

        logger.info("🟢 YouTube 'Dual-Config' Engine initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        if "audio" not in clean_query:
            search_text = f"{clean_query} audio"
        else:
            search_text = clean_query

        cache_key = f"yt_search_dual_config:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                # ИСПОЛЬЗУЕМ ОПЦИИ ДЛЯ ПОИСКА
                with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                    try:
                        return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception as e:
                        logger.error(f"Search Error: {e}", exc_info=True)
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
        
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        for ext in ['.mp3', '.m4a', '.webm']:
            existing = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
            if existing.exists() and existing.stat().st_size > 50000:
                return DownloadResult(success=True, file_path=existing, track_info=track_info)

        url = f"https://www.youtube.com/watch?v={video_id}"

        async with self.semaphore:
            logger.info(f"[YT] Downloading with 'Dual-Config': {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    # ИСПОЛЬЗУЕМ ОПЦИИ ДЛЯ СКАЧИВАНИЯ
                    with yt_dlp.YoutubeDL(self.download_opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Download Error {video_id}: {e}", exc_info=True)
                    return False

            try:
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=120.0)
            except asyncio.TimeoutError:
                return DownloadResult(success=False, error_message="Timeout", track_info=track_info)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Failed", track_info=track_info)

            start_wait = time.time()
            while time.time() - start_wait < 15:
                mp3_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
                if mp3_path.exists() and mp3_path.stat().st_size > 50000:
                    return DownloadResult(success=True, file_path=mp3_path, track_info=track_info)
                
                for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):
                    if path.is_file() and path.stat().st_size > 50000:
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                        
                await asyncio.sleep(1)
            
            return DownloadResult(success=False, error_message="File lost", track_info=track_info)
