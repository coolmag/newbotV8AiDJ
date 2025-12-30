from __future__ import annotations
import asyncio
import logging
import os
import glob
import re
import time  # <--- КРИТИЧЕСКИ ВАЖНЫЙ ИМПОРТ
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
    # Ослабляем список стоп-слов, чтобы находить больше музыки
    FORBIDDEN_WORDS = [
        'tutorial', 'making of', 'lesson', 'course', 
        'podcast', 'backing track', 'karaoke'
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self._ytmusic = YTMusic()
        self.semaphore = asyncio.Semaphore(3)
        self.search_semaphore = asyncio.Semaphore(5)
        
        cookies_content = os.getenv("COOKIES_CONTENT")
        cookie_file_path = None
        
        if cookies_content:
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            logger.info("🍪 Куки успешно загружены из переменной в файл!")

        self.ydl_opts = {
            "quiet": True,
            "format": "bestaudio/best",
            "noplaylist": True,
            "source_address": "0.0.0.0", # Важно для Railway!
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
        }
        if cookie_file_path:
            self.ydl_opts['cookiefile'] = cookie_file_path

        logger.info("YouTubeDownloader initialized")

    def _is_track_valid(self, entry: Dict, decade: Optional[str] = None, is_russian_query: bool = False, strict: bool = True) -> bool:
        if not entry or entry.get('resultType') not in ['song', 'video']: return False
        
        title = entry.get('title', '').lower()
        if any(word in title for word in self.FORBIDDEN_WORDS): return False
        
        duration_sec = entry.get('duration_seconds', 0)
        
        # Если не strict, принимаем практически всё
        if not strict:
            return duration_sec > 20 # Любой трек длиннее 20 секунд
            
        # Строгая проверка
        if not (45 < duration_sec < 1200): return False
        
        if is_russian_query:
            artist_list = entry.get('artists', [])
            artist_name = artist_list[0].get('name', '') if artist_list else ''
            # На Railway часто приходят английские названия для русских треков,
            # поэтому в строгом режиме мы ищем кириллицу, но в мягком - игнорируем это.
            if not bool(re.search('[а-яА-ЯёЁ]', title + artist_name)):
                return False
        return True

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            cache_key = f"yt_search_v11:{query.lower().strip()}:{search_mode}"
            cached = await self._cache.get(cache_key)
            if cached: return cached

            # Стратегии поиска (если первая не сработала, пробуем следующую)
            suffixes = ["", " music", " official", " audio", " remix"]
            is_russian = any(word in query.lower() for word in ['советск', 'русск', 'ссср', 'песни'])
            
            all_valid_tracks = []
            
            for suffix in suffixes:
                actual_query = f"{query}{suffix}"
                logger.info(f"[Search] Trying: '{actual_query}'")
                
                def do_search():
                    try: return self._ytmusic.search(actual_query, filter="songs", limit=limit+5)
                    except: return []

                results = await asyncio.get_running_loop().run_in_executor(None, do_search)
                
                # Сначала пробуем строго
                valid = [e for e in results if self._is_track_valid(e, decade, is_russian, strict=True)]
                
                # Если мало, пробуем мягко
                if len(valid) < 5:
                    valid = [e for e in results if self._is_track_valid(e, decade, is_russian, strict=False)]
                
                all_valid_tracks.extend([self._parse_ytmusic_entry(e) for e in valid])
                
                if len(all_valid_tracks) >= 5: break # Нашли достаточно

            # Если всё еще пусто - аварийный поиск вообще без фильтров
            if not all_valid_tracks:
                logger.warning(f"[Search] Total failure for '{query}', disabling all filters.")
                def emergency_search():
                    try: return self._ytmusic.search(query, limit=10)
                    except: return []
                results = await asyncio.get_running_loop().run_in_executor(None, emergency_search)
                all_valid_tracks = [self._parse_ytmusic_entry(e) for e in results if e.get('videoId')]

            # Уникализация
            unique = []
            seen = set()
            for t in all_valid_tracks:
                if t.identifier not in seen:
                    unique.append(t)
                    seen.add(t.identifier)

            final = unique[:limit]
            if final: await self._cache.set(cache_key, final, ttl=3600)
            return final

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        artists = ", ".join([a['name'] for a in entry.get('artists', []) if a.get('name')])
        # Если артиста нет в поле artists, иногда он в заголовке
        title = entry.get('title', 'Unknown Track')
        if not artists and " - " in title:
            parts = title.split(" - ", 1)
            artists = parts[0]
            title = parts[1]
            
        return TrackInfo(
            identifier=entry['videoId'], 
            title=title, 
            artist=artists or "Unknown Artist",
            duration=int(entry.get('duration_seconds', 0)), 
            source=Source.YOUTUBE,
            thumbnail_url=entry['thumbnails'][-1]['url'] if entry.get('thumbnails') else None
        )

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        cache_key = f"track_info:{video_id}"
        cached_info = await self._cache.get(cache_key)
        if cached_info: return cached_info
        
        loop = asyncio.get_running_loop()
        def do_extract_info():
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(video_id, download=False)
            except Exception: return None
            
        info = await loop.run_in_executor(None, do_extract_info)
        if not info: return None
        
        track_info = TrackInfo.from_yt_info(info)
        await self._cache.set(cache_key, track_info, ttl=86400)
        return track_info

    async def download(self, video_id: str) -> DownloadResult:
        async with self.semaphore:
            track_info = await self.get_track_info(video_id)
            if not track_info:
                return DownloadResult(success=False, error_message="Info failed")
            
            # Проверка кэша ID файла телеграм
            file_id_cache_key = f"file_id:{video_id}"
            cached_file_id = await self._cache.get(file_id_cache_key)
            if cached_file_id:
                return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)
            
            # Проверка локального файла
            existing_path = self._find_downloaded_file(video_id)
            if existing_path:
                 return DownloadResult(success=True, file_path=existing_path, track_info=track_info)

            logger.info(f"[Download] Starting: {video_id}")
            loop = asyncio.get_running_loop()
            
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                        ydl.download([video_id])
                    return True
                except Exception as e: 
                    logger.error(f"Download error {video_id}: {e}")
                    return False
            
            success = await loop.run_in_executor(None, do_download)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Error", track_info=track_info)

            # Ждем появления файла (иногда файловая система лагает)
            final_path = await self.wait_for_download_completion(video_id)
            if not final_path:
                return DownloadResult(success=False, error_message="File lost", track_info=track_info)
            
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        cache_key = f"file_id:{video_id}"
        await self._cache.set(cache_key, file_id, ttl=0) # Вечный кэш для file_id

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        # Ищем точное совпадение
        exact_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if exact_path.exists() and exact_path.stat().st_size > 1024:
            return exact_path
        return None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        start_time = time.time() # Теперь time определен!
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        while time.time() - start_time < timeout:
            if final_path.exists() and final_path.stat().st_size > 1024:
                # Проверяем нет ли .part файлов (значит загрузка еще идет)
                part_files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*.part"))
                if not part_files:
                    return final_path
            await asyncio.sleep(0.5)
        return None

    async def _cleanup_partial(self, video_id: str):
        pass # Реализовать при необходимости