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
    ADAPTER: RAILWAY FINAL STABLE (2026)
    - Cookies from ENV (Fixes 403)
    - Fallback to Video (Fixes 'Requested format not available')
    - iOS Client priority (Better stability)
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # --- RAILWAY COOKIES SETUP ---
        self.cookies_path = Path("cookies/youtube_railway.txt")
        # Адаптировано: проверяем обе переменные окружения, как вы указали
        cookies_content = os.getenv("YT_COOKIES_CONTENT") or os.getenv("COOKIES_CONTENT")
        
        if cookies_content:
            try:
                self.cookies_path.parent.mkdir(exist_ok=True)
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies loaded successfully from Env!")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")
        else:
            logger.warning("⚠️ No Cookies found! Ban risk is high.")

        # SEMAPHORE: 1 download at a time to prevent IP ban
        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)
        
        self._url_cache: Dict[str, str] = {}

        # --- THE FIX CONFIGURATION ---
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            
            # ГЛАВНЫЙ ФИКС: Если нет чистого аудио, качаем видео 480p/360p
            # FFmpeg все равно вырежет из него звук.
            "format": "bestaudio/best[height<=480]/best",
            
            # Не падать, если формат странный
            "ignore_no_formats_error": True,
            
            "extractor_args": {
                "youtube": {
                    # iOS сейчас стабильнее отдает форматы на серверных IP
                    "player_client": ["ios", "android", "web"],
                    "player_skip": ["webpage", "configs", "js"],
                    # Убрали skip dash/hls - принимаем всё!
                }
            },
            
            # Анти-фриз
            "socket_timeout": 30,
            "retries": 10,
            
            # Эмуляция заголовков iPhone
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                "Accept-Language": "en-US,en;q=0.9",
            },

            # Всегда конвертируем в MP3
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True,
            'ignoreerrors': True, # Важно: True, чтобы ловить ошибки внутри кода
        }
        
        if self.cookies_path.exists():
            self.ydl_opts['cookiefile'] = str(self.cookies_path)

        logger.info("🟢 YouTube Final Stable Engine initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        if "audio" not in clean_query:
            search_text = f"{clean_query} audio"
        else:
            search_text = clean_query

        cache_key = f"yt_search_final:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached:
            logger.info(f"[YT Search] Cache HIT for query: '{query}'")
            return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                opts = self.ydl_opts.copy()
                opts['extract_flat'] = True
                # iOS клиент для поиска тоже часто лучше
                opts['extractor_args']['youtube']['player_client'] = ['ios', 'web']
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    try:
                        return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception as e:
                        logger.error(f"Search Error: {e}")
                        return None

            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=25.0)
            except asyncio.TimeoutError:
                logger.error(f"[YT Search] TIMEOUT for query: '{query}'")
                return []
            
            if not res or 'entries' not in res or not res['entries']:
                logger.warning(f"[YT Search] FAILED or NO RESULTS for query: '{query}'.")
                return []
            
            results = []
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
                logger.info(f"[YT Search] Success. Found {len(results)} tracks for query: '{query}'")
                await self._cache.set(cache_key, results, ttl=3600)
            else:
                logger.warning(f"[YT Search] Found entries for '{query}', but all were filtered out (e.g., by duration).")
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
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=120.0)
            except asyncio.TimeoutError:
                logger.error(f"[YT] Download TIMEOUT for {video_id}")
                return DownloadResult(success=False, error_message="Timeout", track_info=track_info)
            
            if not success:
                logger.error(f"[YT] Download FAILED for {video_id}: Check logs for details.")
                return DownloadResult(success=False, error_message="Download Failed", track_info=track_info)

            start_wait = time.time()
            while time.time() - start_wait < 15:
                for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):
                    if path.is_file() and path.stat().st_size > 50000:
                        logger.info(f"[YT] Downloaded and found file: {path.name}")
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                await asyncio.sleep(1)
            
            logger.error(f"[YT] Downloaded file not found after waiting for {video_id}.")
            return DownloadResult(success=False, error_message="File lost", track_info=track_info)
