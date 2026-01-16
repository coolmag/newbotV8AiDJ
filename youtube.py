from __future__ import annotations
import asyncio
import logging
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
    ADAPTER: SOUNDCLOUD UNLIMITED
    - Ищет агрессивно (много треков).
    - Жестко контролирует имена файлов (чтобы не терялись).
    - Качает быстро.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.semaphore = asyncio.Semaphore(5)
        self.search_semaphore = asyncio.Semaphore(5)
        
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
        
        logger.info("🟢 SoundCloud Unlimited Engine initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        """Умный поиск с агрессивным сбором."""
        clean_query = query.lower().strip()
        cache_key = f"sc_search_v5:{clean_query}"
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
                        logger.error(f"SC Search Error: {e}")
                        return None

            res = await loop.run_in_executor(None, do_search)
            
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry: continue
                    
                    tid = str(entry.get('id', ''))
                    if not tid: continue

                    duration = int(entry.get('duration', 0))
                    if duration < 45 or duration > 1200:
                        continue

                    results.append(TrackInfo(
                        identifier=tid,
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('uploader', 'Unknown Artist'),
                        duration=duration,
                        source=Source.YOUTUBE,
                        thumbnail_url=None
                    ))

            if results:
                random.shuffle(results)
                await self._cache.set(cache_key, results, ttl=3600)
            
            return results

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        return None

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        video_id = str(video_id)
        
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id:
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        expected_file = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if expected_file.exists() and expected_file.stat().st_size > 50000:
            return DownloadResult(success=True, file_path=expected_file, track_info=track_info)

        async with self.semaphore:
            logger.info(f"[SC] Downloading: {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    query = f"scsearch1:{video_id}"
                    with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                        ydl.download([query])
                    return True
                except Exception as e:
                    logger.error(f"Download Error {video_id}: {e}")
                    return False

            success = await loop.run_in_executor(None, do_download)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Failed")

            start_wait = time.time()
            while time.time() - start_wait < 30:
                if expected_file.exists() and expected_file.stat().st_size > 50000:
                    logger.info(f"[SC] Success file: {expected_file}")
                    return DownloadResult(success=True, file_path=expected_file, track_info=track_info)
                await asyncio.sleep(1)
            
            logger.error(f"[SC] File not found after download: {expected_file}")
            return DownloadResult(success=False, error_message="File lost after download")

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        return path if path.exists() else None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        return self._find_downloaded_file(video_id)

    async def get_random_cached_tracks(self, limit: int = 10) -> List[TrackInfo]:
        loop = asyncio.get_running_loop()
        def scan_files():
            return list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))
        
        files = await loop.run_in_executor(None, scan_files)
        if not files: return []
        random.shuffle(files)
        tracks = []
        for f in files[:limit]:
            tracks.append(TrackInfo(
                identifier=f.stem, 
                title="Cached Track", 
                artist="Archive", 
                duration=0, 
                source=Source.YOUTUBE
            ))
        return tracks