from __future__ import annotations
import asyncio
import logging
import os
import glob
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
from ytmusicapi import YTMusic

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class SilentLogger:
    def debug(self, msg: str): pass
    def warning(self, msg: str): pass
    def error(self, msg: str): logger.error(f"[yt-dlp] {msg}")

class YouTubeDownloader:
    FORBIDDEN_WORDS = [
        'how to', 'tutorial', 'making of', 'fl studio', 'lesson', 'course', 'mix', 
        'playlist', 'live', 'concert', 'full album', 'dj set', 'remix', 'bootleg',
        'mashup', 'megamix', 'continuous mix', 'non-stop', 'podcast',
        'backing track', 'karaoke'
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self._ytmusic = YTMusic()
        self.semaphore = asyncio.Semaphore(3)
        self.search_semaphore = asyncio.Semaphore(5)
        
        # 1. Достаем куки из переменной Railway (назови её там COOKIES_CONTENT)
        cookies_content = os.getenv("COOKIES_CONTENT")
        cookie_file_path = None
        
        if cookies_content:
            # Создаем файл cookies.txt на лету
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            logger.info("🍪 Куки успешно загружены из переменной в файл!")
        else:
            logger.warning("⚠️ Переменная COOKIES_CONTENT не найдена, пробуем без кук.")

        # 2. Настраиваем yt-dlp
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "logger": SilentLogger(),
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True, # Railway fix
        }
        if cookie_file_path:
            self.ydl_opts['cookiefile'] = cookie_file_path

        logger.info("YouTubeDownloader initialized with ytmusicapi and caching")

    # The _get_dl_opts method is removed as its functionality is now integrated into __init__

    def _is_track_valid(self, entry: Dict, decade: Optional[str] = None, is_russian_query: bool = False) -> bool:
        if not entry or entry.get('resultType') not in ['song', 'video']: return False
        title = entry.get('title', '').lower()
        if any(word in title for word in self.FORBIDDEN_WORDS): return False
        duration_sec = entry.get('duration_seconds', 0)
        if not (45 < duration_sec < 900): return False
        if is_russian_query:
            artist_list = entry.get('artists', [])
            artist_name = artist_list[0].get('name', '') if artist_list else ''
            if not bool(re.search('[а-яА-ЯёЁ]', title + artist_name)):
                return False
        if decade:
            is_year_decade = len(decade) == 5 and decade.endswith('s') and decade[:4].isdigit()
            if is_year_decade:
                year_str = entry.get('year')
                if year_str and year_str.isdigit() and int(year_str) < int(decade[:4]):
                    return False
        return True

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            cache_key = f"yt_search_v9:{query.lower().strip()}:{search_mode}:{decade}"
            cached_tracks = await self._cache.get(cache_key)
            if cached_tracks is not None:
                logger.info(f"[Search] Cache HIT for query '{query}'")
                return cached_tracks

            logger.info(f"[Search] Cache MISS for query '{query}'")
            is_russian_query = any(word in query.lower() for word in ['советск', 'русск', 'ссср'])
            
            if search_mode == 'artist':
                actual_query = f"{query} official songs"
                yt_filter = "songs"
            elif search_mode == 'track':
                actual_query = f"{query} audio"
                yt_filter = "songs"
            else: # genre
                actual_query = f"{query} topic"
                yt_filter = "songs"
            
            logger.info(f"[Search] Performing search: query='{actual_query}', mode='{search_mode}'")
            
            loop = asyncio.get_running_loop()
            def do_search(q: str, f: str) -> List[Dict]:
                try: return self._ytmusic.search(q, filter=f, limit=limit)
                except Exception as e:
                    logger.error(f"YTMusic search failed for '{q}': {e}")
                    return []

            search_results = await loop.run_in_executor(None, do_search, actual_query, yt_filter)
            valid_entries = [e for e in search_results if self._is_track_valid(e, decade, is_russian_query)]
            
            final_tracks = [self._parse_ytmusic_entry(entry) for entry in valid_entries][:limit]
            
            await self._cache.set(cache_key, final_tracks, ttl=3600)
            logger.info(f"[Search] Found {len(final_tracks)} filtered tracks for '{query}'")
            return final_tracks

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        artists = ", ".join([a['name'] for a in entry.get('artists', []) if a.get('name')])
        return TrackInfo(
            identifier=entry['videoId'], title=entry['title'], artist=artists,
            duration=int(entry.get('duration_seconds', 0)), source=Source.YOUTUBE,
            thumbnail_url=entry['thumbnails'][-1]['url'] if entry.get('thumbnails') else None
        )

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        # This method remains largely the same
        cache_key = f"track_info:{video_id}"
        cached_info = await self._cache.get(cache_key)
        if cached_info: return cached_info
        logger.info(f"[TrackInfo] Cache miss. Fetching info for {video_id}")
        loop = asyncio.get_running_loop()
        def do_extract_info():
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(video_id, download=False)
            except Exception as e:
                logger.error(f"[TrackInfo] Failed for {video_id}: {e}")
                return None
        info = await loop.run_in_executor(None, do_extract_info)
        if not info: return None
        track_info = TrackInfo.from_yt_info(info)
        await self._cache.set(cache_key, track_info, ttl=86400)
        return track_info

    async def download(self, video_id: str) -> DownloadResult:
        # This method remains largely the same
        async with self.semaphore:
            track_info = await self.get_track_info(video_id)
            if not track_info:
                return DownloadResult(success=False, error_message="Failed to get track info")
            
            file_id_cache_key = f"file_id:{video_id}"
            cached_file_id = await self._cache.get(file_id_cache_key)
            if cached_file_id:
                return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)
            
            logger.info(f"[Download] Starting download: {video_id}")
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                        ydl.download([video_id])
                    return True
                except Exception: return False
            
            try:
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=300.0)
                if not success:
                    return DownloadResult(success=False, error_message="Download failed", track_info=track_info)
            except asyncio.TimeoutError:
                await self._cleanup_partial(video_id)
                return DownloadResult(success=False, error_message="Timeout", track_info=track_info)

            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error_message="File not found", track_info=track_info)
            
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        cache_key = f"file_id:{video_id}"
        await self._cache.set(cache_key, file_id, ttl=0)
        logger.info(f"Cached file_id for {video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
        files = glob.glob(pattern)
        if files:
            path = Path(files[0])
            if path.exists() and path.stat().st_size > 0: return path
        return None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        """Ожидает полного завершения загрузки файла."""
        logger.info(f"[{video_id}] Waiting for download completion...")
        start_time = time.time()
        
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        while time.time() - start_time < timeout:
            # Проверяем, существует ли финальный файл
            if final_path.exists() and final_path.stat().st_size > 1024:
                # Проверяем, нет ли временных .part файлов
                part_files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*.part"))
                if not part_files:
                    logger.info(f"[{video_id}] Download confirmed complete.")
                    return final_path
            
            await asyncio.sleep(0.5)

        logger.warning(f"[{video_id}] Timeout waiting for download completion.")
        return None

    async def _cleanup_partial(self, video_id: str):
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")
        try:
            files_to_delete = await asyncio.to_thread(glob.glob, pattern)
            for f in files_to_delete:
                await asyncio.to_thread(os.unlink, f)
        except Exception as e:
            logger.warning(f"Error during partial file cleanup for {video_id}: {e}")