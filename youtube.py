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
    ADAPTER: RAILWAY 'YT-DLP DIRECT' STABLE (2026) - The REAL Final Fix
    - Correctly uses cookies for BOTH search and download.
    - Enforces 15MB filesize limit.
    - Clean architecture with opts defined in __init__.
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.cookies_path = Path("cookies/youtube_railway.txt")
        cookies_content = os.getenv("YT_COOKIES_CONTENT") or os.getenv("COOKIES_CONTENT")
        if cookies_content:
            try:
                self.cookies_path.parent.mkdir(exist_ok=True)
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies loaded and prepared.")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)

        # --- ОПЦИИ ДЛЯ ПОИСКА ---
        self.search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 20,
            "retries": 3,
        }
        
        # --- ОПЦИИ ДЛЯ СКАЧИВАНИЯ ---
        self.download_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            "max_filesize": 15 * 1024 * 1024,
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "keepvideo": False,
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'nocheckcertificate': True,
            "socket_timeout": 30,
            "retries": 10,
            "ignoreerrors": True,
        }

        # ПРИМЕНЯЕМ КУКИ К ОБЕИМ КОНФИГУРАЦИЯМ
        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            self.download_opts['cookiefile'] = str(self.cookies_path)
            logger.info("Cookie file applied to both SEARCH and DOWNLOAD configs.")

        logger.info("🟢 YouTube 'YT-DLP Direct' Final Engine initialized.")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        if "audio" not in clean_query: search_text = f"{clean_query} audio"
        else: search_text = clean_query
        cache_key = f"yt_search_direct_final:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached
        
        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            def do_search():
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
                for entry in res.get('entries', []):
                    if not entry: continue
                    results.append(TrackInfo(
                        identifier=str(entry.get('id', '')),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown'),
                        duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE,
                        thumbnail_url=None))
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        video_id = str(video_id).strip()
        
        cached_file_id = await self._cache.get(f"file_id:{video_id}")
        if cached_file_id:
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 1000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown Track", artist="Unknown Artist", duration=0, source=Source.YOUTUBE)

        async with self.semaphore:
            url = f"https://www.youtube.com/watch?v={video_id}"
            loop = asyncio.get_running_loop()

            def do_dl():
                try:
                    with yt_dlp.YoutubeDL(self.download_opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"DL Error: {e}", exc_info=True)
                    return False

            success = await asyncio.wait_for(loop.run_in_executor(None, do_dl), timeout=120.0)

            if success:
                if final_path.exists() and final_path.stat().st_size > 1000:
                    logger.info(f"Download successful. Returning result for {video_id}.")
                    return DownloadResult(success=True, file_path=final_path, track_info=track_info)
            
            return DownloadResult(success=False, error_message="Download failed", track_info=track_info)