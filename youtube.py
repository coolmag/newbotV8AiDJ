from __future__ import annotations
import asyncio
import logging
import os
import glob
from pathlib import Path
from typing import Dict, List, Optional
import yt_dlp
from ytmusicapi import YTMusic
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class SilentLogger:
    def debug(self, msg: str): pass
    def warning(self, msg: str): pass
    def error(self, msg: str): logger.error(f"[yt-dlp] {msg}")

class YouTubeDownloader:
    FORBIDDEN_WORDS = ['tutorial', 'making of', 'lesson', 'course', 'podcast', 'backing track', 'karaoke']

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self._ytmusic = YTMusic()
        
        self.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
        self.search_semaphore = asyncio.Semaphore(5)
        self._download_locks: Dict[str, asyncio.Lock] = {}
        
        cookies_content = os.getenv("COOKIES_CONTENT")
        self.cookie_path = None
        if cookies_content:
            self.cookie_path = "cookies.txt"
            with open(self.cookie_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)

        # --- ABSOLUTE MINIMALIST CONFIG ---
        self.ydl_opts = {
            # Самый простой и надежный формат. FFmpeg вытащит звук, если скачается видео.
            "format": "bestaudio/best",
            
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "logger": SilentLogger(),
            
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            
            "retries": 15,
            "fragment_retries": 15,
            "socket_timeout": 30,
            
            # Оставляем только базовый User-Agent, чтобы не вызывать подозрений
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            
            # Конвертируем в mp3
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'nocheckcertificate': True,
        }
        
        if self.cookie_path: self.ydl_opts['cookiefile'] = self.cookie_path

    async def download(self, video_id: str) -> DownloadResult:
        lock = self._get_file_lock(video_id)
        async with lock:
            path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if path.exists() and path.stat().st_size > 1024:
                if not glob.glob(str(path) + ".*"):
                    info = await self.get_track_info(video_id)
                    return DownloadResult(success=True, file_path=path, track_info=info)

            async with self.semaphore:
                def do_dl():
                    try:
                        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                            ydl.download([video_id])
                        return True
                    except Exception as e:
                        logger.warning(f"DL failed for {video_id}: {e}")
                        return False

                if await asyncio.get_running_loop().run_in_executor(None, do_dl):
                    final_path = await self._wait_for_download_completion(video_id)
                    if final_path:
                        info = await self.get_track_info(video_id)
                        return DownloadResult(success=True, file_path=final_path, track_info=info)
                
                return DownloadResult(success=False, error_message="Download failed or timed out")

    async def _wait_for_download_completion(self, video_id: str, timeout: int = 90) -> Optional[Path]:
        start_time = time.time()
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        while time.time() - start_time < timeout:
            if final_path.exists() and final_path.stat().st_size > 1024:
                # Убедимся, что нет временных файлов .part
                if not glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*.part")):
                    return final_path
            await asyncio.sleep(0.5)
        return None
    
    def _get_file_lock(self, video_id: str) -> asyncio.Lock:
        if video_id not in self._download_locks: self._download_locks[video_id] = asyncio.Lock()
        return self._download_locks[video_id]

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            clean_query = query.lower().strip()
            cache_key = f"yt_search_v35:{clean_query}"
            cached = await self._cache.get(cache_key)
            if cached: return cached

            suffixes = ["", " music"]
            all_tracks = []
            
            for suffix in suffixes:
                q = f"{clean_query}{suffix}"
                def do_search():
                    try:
                        return self._ytmusic.search(q, filter="songs", limit=limit)
                    except: return []

                results = await asyncio.get_running_loop().run_in_executor(None, do_search)
                valid = [self._parse_ytmusic_entry(e) for e in results if self._is_track_valid(e)]
                all_tracks.extend(valid)
                if len(all_tracks) >= limit: break

            unique = list({t.identifier: t for t in all_tracks}.values())
            final = unique[:limit]

            if final: await self._cache.set(cache_key, final, ttl=7200)
            return final

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        return TrackInfo(
            identifier=entry.get('videoId', ''),
            title=entry.get('title', 'Unknown'),
            artist=", ".join([a['name'] for a in entry.get('artists', []) if 'name' in a]),
            duration=entry.get('duration_seconds', 0),
            thumbnail_url=entry.get('thumbnails', [{}])[-1].get('url')
        )

    def _is_track_valid(self, entry: Dict) -> bool:
        if not entry or 'videoId' not in entry or 'duration_seconds' not in entry: return False
        title = entry.get('title', '').lower()
        if any(w in title for w in self.FORBIDDEN_WORDS): return False
        return 45 < entry['duration_seconds'] < 900
    
    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        cache_key = f"info:{video_id}"
        if cached := await self._cache.get(cache_key): return cached
        
        def do_info():
            try: 
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl: return ydl.extract_info(video_id, download=False)
            except: return None
        
        info = await asyncio.get_running_loop().run_in_executor(None, do_info)
        if not info: return None
        track_info = TrackInfo.from_yt_info(info)
        await self._cache.set(cache_key, track_info, ttl=86400)
        return track_info
