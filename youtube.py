from __future__ import annotations
import asyncio
import logging
import time
import random
from pathlib import Path
from typing import List, Optional, Dict

import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER: SOUNDCLOUD EDITION
    Работает стабильно, быстро, без банов IP и без авторизации.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.semaphore = asyncio.Semaphore(5)
        self.search_semaphore = asyncio.Semaphore(10)
        
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True,
            'ignoreerrors': True,
        }
        
        logger.info("🟢 SoundCloud Engine initialized (FREE MODE)")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 15) -> List[TrackInfo]:
        """Поиск на SoundCloud через yt-dlp"""
        clean_query = query.lower().strip()
        cache_key = f"sc_search_v3:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                search_query = f"scsearch{limit}:{clean_query}"
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    try:
                        return ydl.extract_info(search_query, download=False)
                    except Exception as e:
                        logger.error(f"SoundCloud Search Error: {e}")
                        return None

            res = await loop.run_in_executor(None, do_search)
            
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry: continue
                    dur = int(entry.get('duration', 0))
                    if dur > 1200: continue  # Пропускаем длинные сеты

                    results.append(TrackInfo(
                        identifier=entry['id'],
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('uploader', 'Unknown Artist'),
                        duration=dur,
                        source=Source.YOUTUBE,
                        thumbnail_url=None
                    ))

            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            
            return results

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        return None

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id:
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        existing_path = self._find_downloaded_file(video_id)
        if existing_path:
            return DownloadResult(success=True, file_path=existing_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"[SC] Downloading: {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    url = f"scsearch1:{video_id}"
                    with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Download Error: {e}")
                    return False

            success = await loop.run_in_executor(None, do_download)
            
            if not success:
                return DownloadResult(success=False, error_message="SC Download Failed")

            final_path = await self.wait_for_download_completion(video_id)
            if not final_path:
                return DownloadResult(success=False, error_message="File lost")
            
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        for path in self._settings.DOWNLOADS_DIR.glob(f"*{video_id}*.mp3"):
            if path.stat().st_size > 1024:
                return path
        return None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        start_time = time.time()
        while time.time() - start_time < timeout:
            path = self._find_downloaded_file(video_id)
            if path: return path
            await asyncio.sleep(0.5)
        return None

    async def get_random_cached_tracks(self, limit: int = 10) -> List[TrackInfo]:
        loop = asyncio.get_running_loop()
        def scan_files(): return list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))
        files = await loop.run_in_executor(None, scan_files)
        if not files: return []
        random.shuffle(files)
        tracks = []
        for f in files[:limit]:
            tracks.append(TrackInfo(identifier=f.stem, title="Cached Track", artist="SoundCloud Archive", duration=0, source=Source.YOUTUBE))
        return tracks