from __future__ import annotations
import asyncio
import logging
import random
import time
import glob
from pathlib import Path
from typing import List, Optional, Dict

import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER: SOUNDCLOUD UNLIMITED (Robust Edition)
    - Сначала получает URL из поиска, потом качает по URL.
    - Ищет файл в любом формате.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.semaphore = asyncio.Semaphore(5)
        self.search_semaphore = asyncio.Semaphore(5)
        
        # Кэш URL для скачивания (чтобы не искать дважды)
        self._url_cache: Dict[str, str] = {}
        
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
        
        logger.info("🟢 SoundCloud Unlimited Engine initialized (Robust)")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        """Поиск с кэшированием URL."""
        clean_query = query.lower().strip()
        cache_key = f"sc_search_v6:{clean_query}"
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
                    
                    # Сохраняем URL для скачивания
                    url = entry.get('url', '')
                    if url:
                        self._url_cache[tid] = url

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
            
            logger.info(f"[SC] Search '{query}': {len(results)} tracks, {len(self._url_cache)} URLs cached")
            return results

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        return None

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        video_id = str(video_id)
        
        # 1. Проверка кэша file_id
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id:
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        # 2. Проверка существующего файла
        for ext in ['.mp3', '.m4a', '.webm', '.ogg']:
            existing = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
            if existing.exists() and existing.stat().st_size > 50000:
                return DownloadResult(success=True, file_path=existing, track_info=track_info)

        # 3. Получаем URL из кэша или ищем заново
        url = self._url_cache.get(video_id)
        if not url:
            # Быстрый поиск конкретного трека
            loop = asyncio.get_running_loop()
            def find_url():
                try:
                    with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                        info = ydl.extract_info(f"scsearch1:{video_id}", download=False)
                        if info and 'entries' and info['entries']:
                            return info['entries'][0].get('url', '')
                except:
                    pass
                return None
            url = await loop.run_in_executor(None, find_url)

        if not url:
            return DownloadResult(success=False, error_message="URL not found", track_info=track_info)

        async with self.semaphore:
            logger.info(f"[SC] Downloading: {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    # Скачиваем по прямому URL
                    opts = self.ydl_opts.copy()
                    opts['outtmpl'] = str(self._settings.DOWNLOADS_DIR / f"{video_id}.%(ext)s")
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Download Error {video_id}: {e}")
                    return False

            success = await loop.run_in_executor(None, do_download)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Failed", track_info=track_info)

            # 4. Ищем файл (любой с ID в имени)
            start_wait = time.time()
            while time.time() - start_wait < 45:
                # Ищем любой файл с этим ID
                for path in self._settings.DOWNLOADS_DIR.glob(f"*{video_id}*"):
                    if path.is_file() and path.stat().st_size > 50000:
                        logger.info(f"[SC] Found file: {path}")
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                await asyncio.sleep(1)
            
            logger.error(f"[SC] File not found after download: {video_id}")
            return DownloadResult(success=False, error_message="File lost", track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        for path in self._settings.DOWNLOADS_DIR.glob(f"*{video_id}*"):
            if path.is_file() and path.stat().st_size > 50000:
                return path
        return None

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