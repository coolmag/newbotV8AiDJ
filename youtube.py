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
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class SilentLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): logger.error(f"[yt-dlp] {msg}")

class YouTubeDownloader:
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self._ytmusic = YTMusic()
        self.semaphore = asyncio.Semaphore(3)
        
        # Загрузка куки
        cookies_content = os.getenv("COOKIES_CONTENT")
        cookie_file_path = None
        if cookies_content:
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f: f.write(cookies_content)

        # === НАСТРОЙКИ ===
        # Вернул к базовым, но с source_address для Railway
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "logger": SilentLogger(),
            "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True,
            'source_address': '0.0.0.0', # Единственный обязательный фикс для Railway
        }
        if cookie_file_path: self.ydl_opts['cookiefile'] = cookie_file_path
        logger.info("YouTubeDownloader initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        # Упрощенный поиск, как был
        cache_key = f"s:{query}:{search_mode}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        q = f"{query} song" if search_mode != 'track' else query
        loop = asyncio.get_running_loop()
        
        try:
            res = await loop.run_in_executor(None, lambda: self._ytmusic.search(q, filter="songs", limit=limit))
        except: return []

        tracks = []
        for e in res:
            if e.get('videoId'):
                tracks.append(TrackInfo(
                    identifier=e['videoId'],
                    title=e.get('title',''),
                    artist=", ".join([a['name'] for a in e.get('artists',[])]),
                    duration=e.get('duration_seconds',0),
                    thumbnail_url=e['thumbnails'][-1]['url'] if e.get('thumbnails') else None
                ))
        
        await self._cache.set(cache_key, tracks, ttl=3600)
        return tracks

    async def download(self, video_id: str) -> DownloadResult:
        async with self.semaphore:
            # Кэш file_id
            fid = await self._cache.get(f"file_id:{video_id}")
            # Получаем инфо (нужно для Title/Artist)
            loop = asyncio.get_running_loop()
            try:
                info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(self.ydl_opts).extract_info(video_id, download=False))
                ti = TrackInfo.from_yt_info(info)
            except:
                return DownloadResult(False, error_message="Info failed")

            if fid: return DownloadResult(True, file_id=fid, track_info=ti)

            # Скачивание
            logger.info(f"Downloading {video_id}...")
            try:
                await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(self.ydl_opts).download([video_id]))
            except Exception as e:
                return DownloadResult(False, error_message=str(e), track_info=ti)

            # Поиск файла
            path = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
            if os.path.exists(path):
                return DownloadResult(True, file_path=Path(path), track_info=ti)
            return DownloadResult(False, error_message="File missing", track_info=ti)

    async def cache_file_id(self, vid, fid):
        await self._cache.set(f"file_id:{vid}", fid, ttl=0)