from __future__ import annotations
import asyncio
import logging
import os
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
import httpx
import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER: RAILWAY 'AUDIO-ONLY' FINAL (2026)
    - Настроен на скачивание только аудио с ограничением размера.
    - Использует конфигурацию, победившую блокировку скачивания.
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
                logger.info("🍪 Cookies loaded and prepared for SEARCH.")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)

        # --- ОПЦИИ ДЛЯ ПОИСКА (с куками) ---
        self.search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 20,
            "retries": 3,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        }

        # --- ОПЦИИ ДЛЯ СКАЧИВАНИЯ (ФИНАЛЬНАЯ НАСТРОЙКА) ---
        self.download_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
            "max_filesize": 25 * 1024 * 1024,
            "extractor_args": {
                "youtube": { "player_client": ["android_music", "web"] }
            },
            "http_headers": {
                "User-Agent": "com.google.android.apps.youtube.music/6.21.51",
                "X-YouTube-Client-Name": "67",
            },
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            "keepvideo": False,
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "socket_timeout": 30,
            "retries": 10,
            "ignoreerrors": True,
            'nocheckcertificate': True,
        }
        
        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            logger.info("Cookie file applied to SEARCH config.")

        logger.info("🟢 YouTube 'Audio-Only' Engine initialized.")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        if "audio" not in clean_query: search_text = f"{clean_query} audio"
        else: search_text = clean_query
        cache_key = f"yt_search_final_audio:{clean_query}"
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
            except asyncio.TimeoutError: return []
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
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
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        for ext in ['.mp3']: # Ищем только mp3, т.к. все конвертируется
            existing = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
            if existing.exists() and existing.stat().st_size > 20000:
                return DownloadResult(success=True, file_path=existing, track_info=track_info)

        url = f"https://www.youtube.com/watch?v={video_id}"
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(self.download_opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Download Error '{video_id}': {e}", exc_info=True)
                    return False
            try:
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=120.0)
            except asyncio.TimeoutError:
                return DownloadResult(success=False, error_message="Download Timeout")
            
            if not success:
                return DownloadResult(success=False, error_message="Download Failed")

            return await self._wait_for_file(video_id, track_info)

    async def _wait_for_file(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        start_wait = time.time()
        while time.time() - start_wait < 20:
            # Ищем сконвертированный MP3
            mp3_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if mp3_path.is_file():
                try:
                    file_size = mp3_path.stat().st_size
                    MAX_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
                    
                    if file_size > MAX_SIZE:
                        logger.warning(f"File '{mp3_path.name}' is too large ({file_size / 1024 / 1024:.2f}MB). Deleting.")
                        mp3_path.unlink()
                        return DownloadResult(success=False, error_message="File too large", track_info=track_info)

                    if file_size > 20000: # min 20KB
                        logger.info(f"[YT] Downloaded and found file: {mp3_path.name} ({file_size / 1024:.1f}KB)")
                        return DownloadResult(success=True, file_path=mp3_path, track_info=track_info)
                except FileNotFoundError:
                    continue # Файл мог быть удален в процессе, продолжаем
            
            await asyncio.sleep(1)
        return DownloadResult(success=False, error_message="File not found after download", track_info=track_info)
