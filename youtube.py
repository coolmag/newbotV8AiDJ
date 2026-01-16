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
from proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

class SilentLogger:
    def debug(self, msg: str): pass
    def warning(self, msg: str): pass
    def error(self, msg: str): logger.error(f"[yt-dlp] {msg}")

class YouTubeDownloader:
    FORBIDDEN_WORDS = ['tutorial', 'making of', 'lesson', 'course', 'podcast', 'backing track', 'karaoke']

    def __init__(self, settings: Settings, cache_service: CacheService, proxy_manager: ProxyManager):
        self._settings = settings
        self._cache = cache_service
        self._proxy_manager = proxy_manager
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self._ytmusic = YTMusic()
        self.semaphore = asyncio.Semaphore(3)
        self.search_semaphore = asyncio.Semaphore(5)
        
        cookies_content = os.getenv("COOKIES_CONTENT")
        self.cookie_file_path = None
        if cookies_content:
            self.cookie_file_path = "cookies.txt"
            with open(self.cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            logger.info("🍪 Куки успешно загружены!")

        self.base_ydl_opts = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": "bestaudio/best", "logger": SilentLogger(),
            "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True, 
            'socket_timeout': 10, # Уменьшаем таймаут для прокси
            'retries': 2, # Уменьшим, т.к. сами делаем ретраи
        }
        if self.cookie_file_path: 
            self.base_ydl_opts['cookiefile'] = self.cookie_file_path
            
        logger.info("YouTubeDownloader initialized (Proxy Rotation Mode)")

    def _get_ydl_opts(self) -> dict:
        """Возвращает копию базовых настроек с новым прокси."""
        opts = self.base_ydl_opts.copy()
        proxy = self._proxy_manager.get_proxy()
        if proxy:
            opts['proxy'] = proxy
            logger.info(f"Using proxy: {proxy}")
        return opts

    async def _execute_yt_dlp(self, video_id: str, download: bool = True, max_retries: int = 20):
        for i in range(max_retries):
            opts = self._get_ydl_opts()
            try:
                async def dlp_task():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        if download:
                            await asyncio.get_running_loop().run_in_executor(None, ydl.download, [video_id])
                            return True
                        else:
                            info = await asyncio.get_running_loop().run_in_executor(None, ydl.extract_info, video_id, False)
                            return info
                
                result = await asyncio.wait_for(dlp_task(), timeout=45.0)
                return result

            except asyncio.TimeoutError:
                logger.warning(f"Global timeout reached for proxy {opts.get('proxy')}. Retrying with new proxy ({i+1}/{max_retries})...")
                self._proxy_manager.report_dead_proxy(opts.get('proxy'))
                continue

            except Exception as e:
                error_str = str(e).lower()
                if any(err in error_str for err in ["proxy", "timeout", "connection refused", "403", "407", "connection aborted", "remote end closed", "requested format is not available"]):
                    logger.warning(f"Proxy error with {opts.get('proxy')}: {e}. Retrying with new proxy ({i+1}/{max_retries})...")
                    self._proxy_manager.report_dead_proxy(opts.get('proxy'))
                    await asyncio.sleep(1)
                    continue
                else:
                    logger.error(f"Non-proxy download error: {e}")
                    return None
        
        logger.error(f"Failed to download/extract info for {video_id} after {max_retries} attempts.")
        return None

    async def get_track_info(self, video_id: str) -> Optional[TrackInfo]:
        cache_key = f"track_info:{video_id}"
        cached_info = await self._cache.get(cache_key)
        if cached_info: return cached_info
        
        info = await self._execute_yt_dlp(video_id, download=False)
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

            logger.info(f"[Download] Starting download for: {video_id} with proxy rotation")
            
            success = await self._execute_yt_dlp(video_id, download=True)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Error (All proxies failed)", track_info=track_info)

            final_path = await self.wait_for_download_completion(video_id)
            if not final_path:
                # Это может случиться, если yt-dlp завершился с 0, но файл не создал (например, ERROR: The downloaded file is empty)
                # Попробуем еще раз с другим прокси, на всякий случай
                logger.warning(f"File not found after download for {video_id}, trying one more time...")
                success = await self._execute_yt_dlp(video_id, download=True, max_retries=1)
                if not success:
                     return DownloadResult(success=False, error_message="File lost after download", track_info=track_info)
                final_path = await self.wait_for_download_completion(video_id)
                if not final_path:
                     return DownloadResult(success=False, error_message="File still lost", track_info=track_info)

            return DownloadResult(success=True, file_path=final_path, track_info=track_info)
    
    # ... Остальные методы без изменений (search, _parse_ytmusic_entry и т.д.) ...
    # ... (Они не используют прокси напрямую) ...

    def _is_track_valid(self, entry: Dict, decade: Optional[str] = None, is_russian_query: bool = False, strict: bool = True) -> bool:
        if not entry: return False
        res_type = entry.get('resultType', '').lower()
        if res_type and res_type not in ['song', 'video']:
            return False
        title = str(entry.get('title', '')).lower()
        if any(word in title for word in self.FORBIDDEN_WORDS): return False
        try:
            duration_sec = int(entry.get('duration_seconds', 0))
        except (ValueError, TypeError):
            duration_sec = 0
        if strict:
            if not (45 < duration_sec < 900): return False
        else:
            if duration_sec > 0 and duration_sec < 20: return False
        if is_russian_query:
            artist_list = entry.get('artists', [])
            artist_name = ""
            if isinstance(artist_list, list) and artist_list:
                artist_name = artist_list[0].get('name', '')
            check_str = (title + str(artist_name)).lower()
            if not bool(re.search('[а-яА-ЯёЁ]', check_str)):
                if strict: return False
        return True

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        async with self.search_semaphore:
            clean_query = query.lower().strip()
            cache_key = f"yt_search_v15_proxy:{clean_query}:{search_mode}"
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
                        if not res:
                            res = self._ytmusic.search(actual_query, filter="videos", limit=limit+5)
                        return res
                    except Exception as e: 
                        logger.warning(f"YTMusic search error: {e}")
                        return []
                results = await asyncio.get_running_loop().run_in_executor(None, do_search)
                valid = [e for e in results if self._is_track_valid(e, decade, is_russian, strict=True)]
                if len(valid) < 3:
                    valid = [e for e in results if self._is_track_valid(e, decade, is_russian, strict=False)]
                all_valid_tracks.extend([self._parse_ytmusic_entry(e) for e in valid])
                if len(all_valid_tracks) >= limit: break
            if not all_valid_tracks:
                logger.warning(f"[Search] Strict search failed for '{query}', trying emergency fallback.")
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
            if final: 
                await self._cache.set(cache_key, final, ttl=3600)
            return final

    def _parse_ytmusic_entry(self, entry: Dict) -> TrackInfo:
        artists_raw = entry.get('artists', [])
        if isinstance(artists_raw, list):
            artists = ", ".join([str(a.get('name', '')) for a in artists_raw if a.get('name')])
        else:
            artists = str(artists_raw)
        title = str(entry.get('title', 'Unknown Track'))
        if (not artists or artists == "Unknown Artist") and " - " in title:
            try:
                parts = title.split(" - ", 1)
                artists = parts[0].strip()
                title = parts[1].strip()
            except: pass
        try:
            dur = int(entry.get('duration_seconds', 0))
        except:
            dur = 0
        thumbs = entry.get('thumbnails', [])
        thumb_url = thumbs[-1]['url'] if thumbs and isinstance(thumbs, list) else None
        return TrackInfo(
            identifier=str(entry.get('videoId', '')), 
            title=title, 
            artist=artists or "Unknown Artist",
            duration=dur, 
            source=Source.YOUTUBE,
            thumbnail_url=thumb_url
        )

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

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

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    async def get_random_cached_tracks(self, limit: int = 10) -> List[TrackInfo]:
        loop = asyncio.get_running_loop()
        def scan_files():
            try:
                files = list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))
                random.shuffle(files)
                return files
            except ImportError:
                return list(self._settings.DOWNLOADS_DIR.glob("*.mp3"))

        files = await loop.run_in_executor(None, scan_files)
        if not files: return []
        selected_files = files[:limit * 2]
        tracks = []
        for file_path in selected_files:
            if len(tracks) >= limit: break
            video_id = file_path.stem
            info = await self.get_track_info(video_id)
            if info:
                tracks.append(info)
            else:
                tracks.append(TrackInfo(
                    identifier=video_id,
                    title=f"Cached Track {video_id[-4:]}",
                    artist="Offline Archive",
                    duration=0,
                    source=Source.YOUTUBE
                ))
        return tracks