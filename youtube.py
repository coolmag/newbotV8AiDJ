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
import httpx

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
        self.semaphore = asyncio.Semaphore(2)
        self.search_semaphore = asyncio.Semaphore(5)
        
        cookies_content = os.getenv("COOKIES_CONTENT")
        cookie_file_path = None
        if cookies_content:
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookies_content)
            logger.info("🍪 Куки загружены (Стратегия: Проброс заголовков)")

        self.ydl_opts = {
            "quiet": True, 
            "no_warnings": True, 
            "noplaylist": True,
            "format": "bestaudio/best",
            "logger": SilentLogger(),
            'nocheckcertificate': True, 
            'socket_timeout': 60,
            'retries': 10,
            'fragment_retries': 10,
            'source_address': '0.0.0.0',
        }
        
        if cookie_file_path: 
            self.ydl_opts['cookiefile'] = cookie_file_path
            
        logger.info("YouTubeDownloader initialized (Strategy: Header Forwarding)")

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        async with self.semaphore:
            if not track_info:
                track_info = await self.get_track_info(video_id)
            if not track_info:
                return DownloadResult(success=False, error_message="Info failed")

            file_id_cache_key = f"file_id:{video_id}"
            cached_file_id = await self._cache.get(file_id_cache_key)
            if cached_file_id:
                return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

            existing_path = self._find_downloaded_file(video_id)
            if existing_path:
                return DownloadResult(success=True, file_path=existing_path, track_info=track_info)

            logger.info(f"[Download] Stage 1/3: Getting direct URL for {video_id}")
            
            info = None
            direct_url = None
            http_headers = None
            try:
                loop = asyncio.get_running_loop()
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(video_id, download=False))
                
                best_audio = next((f for f in reversed(info.get('formats', [])) 
                                   if f.get('acodec') != 'none' and f.get('vcodec') == 'none'), None)
                
                if best_audio:
                    direct_url = best_audio.get('url')
                    http_headers = best_audio.get('http_headers')
                else: # Fallback
                     direct_url = info.get('url')
                     http_headers = info.get('http_headers')

            except Exception as e:
                logger.error(f"URL extraction failed for {video_id}: {e}")
                return DownloadResult(success=False, error_message="URL Extraction Failed", track_info=track_info)

            if not direct_url or not http_headers:
                logger.error(f"No direct URL or headers found for {video_id}")
                return DownloadResult(success=False, error_message="No Direct URL/Headers", track_info=track_info)

            logger.info(f"[Download] Stage 2/3: Downloading from URL with httpx...")

            temp_file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.temp_download"
            try:
                # Используем заголовки, полученные от yt-dlp
                async with httpx.AsyncClient(timeout=60.0, http2=True) as client:
                    async with client.stream("GET", direct_url, headers=http_headers, follow_redirects=True) as response:
                        response.raise_for_status()
                        with open(temp_file_path, 'wb') as f:
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)
                
                if not temp_file_path.exists() or temp_file_path.stat().st_size < 1024:
                    raise Exception("Downloaded file is empty or too small")

            except Exception as e:
                logger.error(f"httpx download failed for {video_id}: {e}")
                if temp_file_path.exists(): os.unlink(temp_file_path)
                return DownloadResult(success=False, error_message="HTTPX Download Failed", track_info=track_info)
            
            logger.info(f"[Download] Stage 3/3: Converting to MP3 with FFmpeg...")
            final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            try:
                ffmpeg_proc = await asyncio.create_subprocess_exec(
                    'ffmpeg',
                    '-i', str(temp_file_path),
                    '-codec:a', 'libmp3lame',
                    '-q:a', '2', # ~192kbps VBR
                    '-y',
                    str(final_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await ffmpeg_proc.communicate()
                if ffmpeg_proc.returncode != 0:
                    # Попытка определить, был ли файл просто скопирован (если исходник уже был mp3)
                    if "Invalid data found when processing input" in stderr.decode():
                         raise Exception(f"FFmpeg failed: Invalid data in source file. {stderr.decode()}")
                    else: # Другая ошибка ffmpeg
                         raise Exception(f"FFmpeg failed: {stderr.decode()}")

            except Exception as e:
                logger.error(f"FFmpeg conversion failed for {video_id}: {e}")
                return DownloadResult(success=False, error_message="FFmpeg Failed", track_info=track_info)
            finally:
                 if temp_file_path.exists(): os.unlink(temp_file_path)

            if not final_path.exists() or final_path.stat().st_size < 1024:
                logger.error(f"Final file is missing or empty for {video_id}")
                return DownloadResult(success=False, error_message="File Lost Post-Conversion", track_info=track_info)

            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

    # --- Остальные методы без изменений ---
            
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
            cache_key = f"yt_search_v_header_fwd:{clean_query}:{search_mode}" 
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

    async def cache_file_id(self, video_id: str, file_id: str):
        await self._cache.set(f"file_id:{video_id}", file_id, ttl=0)

    async def invalidate_cache(self, video_id: str):
        await self._cache.delete(f"file_id:{video_id}")

    def _find_downloaded_file(self, video_id: str) -> Optional[Path]:
        exact_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if exact_path.exists() and exact_path.stat().st_size > 1024: return exact_path
        return None

    async def wait_for_download_completion(self, video_id: str, timeout: int = 45) -> Optional[Path]:
        # Этот метод больше не нужен при ручной конвертации, но оставим на всякий случай
        start_time = time.time()
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        while time.time() - start_time < timeout:
            if final_path.exists() and final_path.stat().st_size > 1024:
                return final_path
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
            else:
                tracks.append(TrackInfo(
                    identifier=video_id,
                    title=f"Cached Track {video_id[-4:]}",
                    artist="Offline Archive",
                    duration=0,
                    source=Source.YOUTUBE
                ))
        return tracks