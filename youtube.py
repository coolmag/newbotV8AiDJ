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
    def error(self, msg: str): 
        # Фильтруем спам ошибок, чтобы не пугать, если ретрай сработает
        if "Did not get any data blocks" not in msg:
            logger.error(f"[yt-dlp] {msg}")

class YouTubeDownloader:
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

        # --- SURGICAL FIX 2026 ---
        self.ydl_opts = {
            # Приоритет m4a (он родной для YouTube), потом любой
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "logger": SilentLogger(),
            
            # СЕТЕВАЯ ХИРУРГИЯ
            "socket_timeout": 30,
            "retries": 20,              # Долбим до победного
            "fragment_retries": 20,     # Если кусок не скачался - пробуем снова
            "skip_unavailable_fragments": False,
            
            # ВАЖНО: Размер буфера. 10Мб притворяются плеером.
            "http_chunk_size": 10485760, 
            
            # Принудительный IPv4 (IPv6 у гугла часто в бане на хостингах)
            "source_address": "0.0.0.0", 
            
            # Маскировка заголовков
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            
            # Имитация мобильного приложения (самый низкий шанс бана)
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios"], # WEB УБРАН СПЕЦИАЛЬНО
                    "player_skip": ["configs", "webview", "js"],
                    "skip": ["dash", "hls"]
                }
            },
            
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'nocheckcertificate': True,
        }
        if self.cookie_path: self.ydl_opts['cookiefile'] = self.cookie_path

    def _get_file_lock(self, video_id: str) -> asyncio.Lock:
        if video_id not in self._download_locks: self._download_locks[video_id] = asyncio.Lock()
        return self._download_locks[video_id]

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            clean = query.lower().strip()
            cache_key = f"search_v29:{clean}"
            if cached := await self._cache.get(cache_key): return cached

            def do_s():
                try: return self._ytmusic.search(query, filter="songs", limit=limit)
                except: return []

            res = await asyncio.get_running_loop().run_in_executor(None, do_s)
            tracks = []
            for r in res:
                if r.get('videoId'):
                    tracks.append(TrackInfo(
                        identifier=r['videoId'],
                        title=r.get('title', 'Unknown'),
                        artist=", ".join([a['name'] for a in r.get('artists', [])]),
                        duration=r.get('duration_seconds', 0),
                        thumbnail_url=r.get('thumbnails', [{}])[-1].get('url')
                    ))
            
            if tracks: await self._cache.set(cache_key, tracks, ttl=3600)
            return tracks

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        cache_key = f"info:{video_id}"
        if cached := await self._cache.get(cache_key): return cached
        
        def fetch():
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl: 
                    return ydl.extract_info(video_id, download=False)
            except: return None
        
        info = await asyncio.get_running_loop().run_in_executor(None, fetch)
        if info:
            t = TrackInfo.from_yt_info(info)
            await self._cache.set(cache_key, t, ttl=86400)
            return t
        return None

    async def download(self, video_id: str) -> DownloadResult:
        lock = self._get_file_lock(video_id)
        async with lock:
            path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            
            # Проверка
            if path.exists() and path.stat().st_size > 5000:
                # Проверяем, не битый ли файл (нет .part)
                if not glob.glob(str(path) + ".*"):
                    info = await self.get_track_info(video_id)
                    return DownloadResult(success=True, file_path=path, track_info=info)

            async with self.semaphore:
                def try_dl():
                    try:
                        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl: 
                            ydl.download([video_id])
                        return True
                    except Exception as e:
                        logger.warning(f"DL Attempt failed {video_id}: {e}")
                        return False

                # Пытаемся скачать в отдельном потоке
                success = await asyncio.get_running_loop().run_in_executor(None, try_dl)
                
                if success:
                    # Ждем финализации FFmpeg
                    start = time.time()
                    while time.time() - start < 60:
                        if path.exists() and path.stat().st_size > 5000:
                            if not glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*.part")):
                                info = await self.get_track_info(video_id)
                                return DownloadResult(success=True, file_path=path, track_info=info)
                        await asyncio.sleep(0.5)
                
                return DownloadResult(success=False, error_message="Failed")

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        return path if path.exists() else None
