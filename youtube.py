from __future__ import annotations
import asyncio
import logging
import os
import glob
import re
import time
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
from ytmusicapi import YTMusic

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

# Заглушка, чтобы не мусорить в логах
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
        self.semaphore = asyncio.Semaphore(2) # Снижаем нагрузку до 2 потоков
        self.search_semaphore = asyncio.Semaphore(5)
        
        # Загружаем куки (ОБЯЗАТЕЛЬНО для Railway)
        cookies_content = os.getenv("COOKIES_CONTENT")
        cookie_file_path = None
        if cookies_content:
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            logger.info("🍪 Куки загружены (Режим сопротивления)")

        self.ydl_opts = {
            "quiet": True, 
            "no_warnings": True, 
            "noplaylist": True,
            "format": "bestaudio/best", # Берем лучшее из доступного
            "logger": SilentLogger(),
            
            # Конвертируем в MP3
            "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
            
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            
            # --- АНТИ-БЛОК НАСТРОЙКИ ---
            'nocheckcertificate': True, 
            'socket_timeout': 60,       # Ждем дольше
            'retries': 20,              # Пытаемся чаще
            'fragment_retries': 20,
            'skip_unavailable_fragments': True, # Если кусок битый - пропускаем, но качаем остальное
            
            # Притворяемся старым добрым десктопным хромом (с куками это работает лучше всего)
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            
            'source_address': '0.0.0.0', # IPv4
        }
        
        if cookie_file_path: 
            self.ydl_opts['cookiefile'] = cookie_file_path
            
        logger.info("YouTubeDownloader initialized (Protocol: Freedom)")

    def _is_track_valid(self, entry: Dict, decade: Optional[str] = None, is_russian_query: bool = False, strict: bool = True) -> bool:
        if not entry: return False
        res_type = entry.get('resultType', '').lower()
        if res_type and res_type not in ['song', 'video']: return False
        title = str(entry.get('title', '')).lower()
        if any(word in title for word in self.FORBIDDEN_WORDS): return False
        try: duration_sec = int(entry.get('duration_seconds', 0))
        except (ValueError, TypeError): duration_sec = 0
        if strict:
            if not (45 < duration_sec < 900): return False
        else:
            if duration_sec > 0 and duration_sec < 20: return False
        if is_russian_query:
            artist_list = entry.get('artists', [])
            artist_name = ""
            if isinstance(artist_list, list) and artist_list: artist_name = artist_list[0].get('name', '')
            check_str = (title + str(artist_name)).lower()
            if not bool(re.search('[а-яА-ЯёЁ]', check_str)):
                if strict: return False
        return True

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            clean_query = query.lower().strip()
            cache_key = f"yt_search_v35:{clean_query}:{search_mode}" 
            cached = await self._cache.get(cache_key)
            if cached: return cached
            suffixes = ["", " music", " official audio"]
            is_russian = any(word in clean_query for word in ['советск', 'русск', 'ссср', 'песни', 'хиты'])
            all_valid_tracks = []
            
            for suffix in suffixes:
                actual_query = f"{query}{suffix}"
                def do_search():
                    try: 
                        res = self._ytmusic.search(actual_query, filter="songs", limit=limit+5)
                        if not res: res = self._ytmusic.search(actual_query, filter="videos", limit=limit+5)
                        return res
                    except Exception as e: 
                        logger.warning(f"YTMusic search error: {e}")
                        return []
                results = await asyncio.get_running_loop().run_in_executor(None, do_search)
                valid = [e for e in results if self._is_track_valid(e, decade, is_russian, strict=True)]
                if len(valid) < 3: valid = [e for e in results if self._is_track_valid(e, decade, is_russian, strict=False)]
                all_valid_tracks.extend([self._parse_ytmusic_entry(e) for e in valid])
                if len(all_valid_tracks) >= limit: break

            if not all_valid_tracks:
                def emergency_search():
                    try: return self._ytmusic.search(query, limit=10)
                    except: return []
                results = await asyncio.get_running_loop().run_in_executor(None, emergency_search)
                all_valid_tracks = [self._parse_ytmusic_entry(e) for e in results if self._is_track_valid(e, strict=False)]

            unique = []
            seen = set()
            for t in all_valid_tracks:
                if t.identifier and t.identifier not in seen:
                    unique.append(t)
                    seen.add(t.identifier)
            final = unique[:limit]
            if final: await self._cache.set(cache_key, final, ttl=3600)
            return final

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        artists_raw = entry.get('artists', [])
        if isinstance(artists_raw, list): artists = ", ".join([str(a.get('name', '')) for a in artists_raw if a.get('name')])
        else: artists = str(artists_raw)
        title = str(entry.get('title', 'Unknown Track'))
        if (not artists or artists == "Unknown Artist") and " - " in title:
            try:
                parts = title.split(" - ", 1)
                artists = parts[0].strip()
                title = parts[1].strip()
            except: pass
        try: dur = int(entry.get('duration_seconds', 0))
        except: dur = 0
        thumbs = entry.get('thumbnails', [])
        thumb_url = thumbs[-1]['url'] if thumbs and isinstance(thumbs, list) else None
        return TrackInfo(
            identifier=str(entry.get('videoId', '')), 
            title=title, artist=artists or "Unknown Artist", duration=dur, source=Source.YOUTUBE, thumbnail_url=thumb_url
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

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        async with self.semaphore:
            if not track_info:
                track_info = await self.get_track_info(video_id)

            if not track_info: return DownloadResult(success=False, error_message="Info failed")
            
            file_id_cache_key = f"file_id:{video_id}"
            cached_file_id = await self._cache.get(file_id_cache_key)
            if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)
            
            existing_path = self._find_downloaded_file(video_id)
            if existing_path: return DownloadResult(success=True, file_path=existing_path, track_info=track_info)
            
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
            if not success: return DownloadResult(success=False, error_message="Download Error", track_info=track_info)

            final_path = await self.wait_for_download_completion(video_id)
            if not final_path: return DownloadResult(success=False, error_message="File lost", track_info=track_info)
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        exact_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if exact_path.exists() and exact_path.stat().st_size > 1024: return exact_path
        return None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        start_time = time.time()
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        while time.time() - start_time < timeout:
            if final_path.exists() and final_path.stat().st_size > 1024:
                part_files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*.part"))
                if not part_files: return final_path
            await asyncio.sleep(0.5)
        return None

    async def get_random_cached_tracks(self, limit: int = 10) -> List[TrackInfo]:
        loop = asyncio.get_running_loop()
        def scan_files():
            return list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))
        
        files = await loop.run_in_executor(None, scan_files)
        if not files: return []
        random.shuffle(files)
        selected_files = files[:limit * 2]
        tracks = []
        for file_path in selected_files:
            if len(tracks) >= limit: break
            video_id = file_path.stem
            info = await self.get_track_info(video_id)
            if info: tracks.append(info)
            else: tracks.append(TrackInfo(identifier=video_id, title=f"Cached {video_id}", artist="Offline", duration=0))
        return tracks