from __future__ import annotations
import asyncio
import logging
import os
import glob
import re
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
        
        # 1. Загрузка кук из переменной окружения
        cookies_content = os.getenv("COOKIES_CONTENT")
        cookie_file_path = None
        if cookies_content:
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            logger.info("🍪 Куки успешно загружены из переменной в файл!")

        # 2. Оптимальная настройка yt-dlp для Railway (Fix 403 и Formats)
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
            'nocheckcertificate': True,
            'geo_bypass': True,
            'source_address': '0.0.0.0', # Принудительно IPv4
            
            # Стабильный обход через эмуляцию Android
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                    'player_skip': ['webpage', 'configs', 'js'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            }
        }
        
        if cookie_file_path:
            self.ydl_opts['cookiefile'] = cookie_file_path

        logger.info("YouTubeDownloader initialized")

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
        return True

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            cache_key = f"yt_search_v11:{query.lower().strip()}:{search_mode}:{decade}"
            cached_tracks = await self._cache.get(cache_key)
            if cached_tracks is not None:
                return cached_tracks

            is_russian_query = any(word in query.lower() for word in ['советск', 'русск', 'ссср'])
            actual_query = f"{query} songs" if search_mode != 'track' else query
            
            loop = asyncio.get_running_loop()
            def do_search():
                try: return self._ytmusic.search(actual_query, filter="songs", limit=limit)
                except Exception: return []

            search_results = await loop.run_in_executor(None, do_search)
            valid_entries = [e for e in search_results if self._is_track_valid(e, decade, is_russian_query)]
            final_tracks = [self._parse_ytmusic_entry(entry) for entry in valid_entries][:limit]
            
            await self._cache.set(cache_key, final_tracks, ttl=3600)
            return final_tracks

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        artists = ", ".join([a['name'] for a in entry.get('artists', []) if a.get('name')])
        return TrackInfo(
            identifier=entry['videoId'], title=entry['title'], artist=artists,
            duration=int(entry.get('duration_seconds', 0)), source=Source.YOUTUBE,
            thumbnail_url=entry['thumbnails'][-1]['url'] if entry.get('thumbnails') else None
        )

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        cache_key = f"track_info_v3:{video_id}"
        cached_info = await self._cache.get(cache_key)
        if cached_info: return cached_info
        
        loop = asyncio.get_running_loop()
        def do_extract_info():
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(video_id, download=False)
            except Exception as e:
                logger.error(f"[TrackInfo] Error for {video_id}: {e}")
                return None
                
        info = await loop.run_in_executor(None, do_extract_info)
        if not info: return None
        track_info = TrackInfo.from_yt_info(info)
        await self._cache.set(cache_key, track_info, ttl=86400)
        return track_info

    async def download(self, video_id: str) -> DownloadResult:
        async with self.semaphore:
            track_info = await self.get_track_info(video_id)
            if not track_info:
                return DownloadResult(success=False, error_message="Metadata failed")
            
            file_id_cache_key = f"file_id:{video_id}"
            cached_file_id = await self._cache.get(file_id_cache_key)
            if cached_file_id:
                return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)
            
            logger.info(f"[Download] Starting: {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                        ydl.download([video_id])
                    return True
                except Exception as e: 
                    logger.error(f"Download Error {video_id}: {e}")
                    return False
            
            try:
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=240.0)
                if not success:
                    return DownloadResult(success=False, error_message="yt-dlp failed", track_info=track_info)
            except asyncio.TimeoutError:
                self._cleanup_partial(video_id)
                return DownloadResult(success=False, error_message="Timeout", track_info=track_info)

            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error_message="File not found", track_info=track_info)
            
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
        files = glob.glob(pattern)
        if files:
            path = Path(files[0])
            if path.exists() and path.stat().st_size > 0: return path
        return None

    def _cleanup_partial(self, video_id: str):
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")
        for f in glob.glob(pattern):
            try: os.unlink(f)
            except Exception: pass
