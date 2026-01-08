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
            logger.info("🍪 Cookies loaded.")

        # --- CLASSIC STABLE CONFIG ---
        self.ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "logger": SilentLogger(),
            
            # Конвертация в MP3
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            
            # Сеть
            'nocheckcertificate': True, 
            'socket_timeout': 30, 
            'retries': 10,
            
            # Притворяемся обычным браузером (Самая надежная защита)
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }
        
        if self.cookie_path: self.ydl_opts['cookiefile'] = self.cookie_path

    def _get_file_lock(self, video_id: str) -> asyncio.Lock:
        if video_id not in self._download_locks: self._download_locks[video_id] = asyncio.Lock()
        return self._download_locks[video_id]

    def _is_track_valid(self, entry: Dict, strict: bool = True) -> bool:
        if not entry: return False
        if entry.get('resultType') not in ['song', 'video']: return False
        title = str(entry.get('title', '')).lower()
        if any(w in title for w in self.FORBIDDEN_WORDS): return False
        try: dur = int(entry.get('duration_seconds', 0))
        except: dur = 0
        if strict: return 45 < dur < 900
        return dur > 20

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            clean_query = query.lower().strip()
            # Сброс кэша поиска (v30)
            cache_key = f"yt_search_v30:{clean_query}"
            if cached := await self._cache.get(cache_key): return cached

            suffixes = ["", " music"]
            all_tracks = []
            
            for suffix in suffixes:
                q = f"{clean_query}{suffix}"
                def do_search():
                    try:
                        res = self._ytmusic.search(q, filter="songs", limit=limit)
                        if not res: res = self._ytmusic.search(q, filter="videos", limit=limit)
                        return res
                    except: return []

                results = await asyncio.get_running_loop().run_in_executor(None, do_search)
                # Парсим
                valid = []
                for e in results:
                    if self._is_track_valid(e, strict=True):
                        valid.append(self._parse_ytmusic_entry(e))
                
                all_tracks.extend(valid)
                if len(all_tracks) >= limit: break

            # Уникальность
            unique = []
            seen = set()
            for t in all_tracks:
                if t.identifier not in seen:
                    unique.append(t)
                    seen.add(t.identifier)

            final = unique[:limit]
            if final: await self._cache.set(cache_key, final, ttl=3600)
            return final

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        artists_raw = entry.get('artists', [])
        if isinstance(artists_raw, list):
            artists = ", ".join([str(a.get('name', '')) for a in artists_raw if a.get('name')])
        else: artists = str(artists_raw)
        title = str(entry.get('title', 'Unknown'))
        try: dur = int(entry.get('duration_seconds', 0))
        except: dur = 0
        thumbs = entry.get('thumbnails', [])
        thumb = thumbs[-1]['url'] if thumbs and isinstance(thumbs, list) else None
        return TrackInfo(identifier=str(entry.get('videoId', '')), title=title, artist=artists, duration=dur, thumbnail_url=thumb)

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        cache_key = f"track_info:{video_id}"
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

    async def download(self, video_id: str) -> DownloadResult:
        lock = self._get_file_lock(video_id)
        async with lock:
            path = self._find_downloaded_file(video_id)
            info = await self.get_track_info(video_id)
            if path: return DownloadResult(success=True, file_path=path, track_info=info)

            async with self.semaphore:
                def do_dl():
                    try:
                        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl: ydl.download([video_id])
                        return True
                    except Exception as e: 
                        logger.error(f"DL Error {video_id}: {e}")
                        return False
                
                # Запускаем загрузку
                if await asyncio.get_running_loop().run_in_executor(None, do_dl):
                    final_path = await self.wait_for_download_completion(video_id)
                    if final_path: return DownloadResult(success=True, file_path=final_path, track_info=info)
                
                return DownloadResult(success=False, error_message="Failed", track_info=info)

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        p = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        return p if p.exists() and p.stat().st_size > 1024 else None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        start = time.time()
        p = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        while time.time() - start < timeout:
            if p.exists() and p.stat().st_size > 1024:
                if not glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*.part")): return p
            await asyncio.sleep(0.5)
        return None