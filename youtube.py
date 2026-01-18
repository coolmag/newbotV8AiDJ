from __future__ import annotations
import asyncio
import logging
import os
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
import httpx
import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER: RAILWAY 'PIPED' FINAL (2026)
    - Основной метод скачивания через Piped API.
    - Резервный метод через yt-dlp с минимальными настройками.
    - Поиск с куками.
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.cookies_path = Path("cookies/youtube_railway.txt")
        cookies_content = os.getenv("YT_COOKIES_CONTENT") or os.getenv("COOKIES_CONTENT")
        if cookies_content:
            try:
                self.cookies_path.parent.mkdir(exist_ok=True)
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies loaded and prepared for SEARCH.")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)

        # Опции для поиска (с куками)
        self.search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 20,
            "retries": 3,
        }
        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            logger.info("Cookie file applied to SEARCH config.")
            
        # Опции для резервного скачивания
        self.ytdlp_fallback_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "worstaudio/worst",
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "socket_timeout": 30,
            "retries": 3,
            "ignoreerrors": True,
            'nocheckcertificate': True,
        }

        logger.info("🟢 YouTube 'Piped' Engine initialized.")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        if "audio" not in clean_query: search_text = f"{clean_query} audio"
        else: search_text = clean_query
        cache_key = f"yt_search_piped:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached
        
        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            def do_search():
                with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                    try:
                        return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception: return None
            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=25.0)
            except asyncio.TimeoutError: return []
            
            results = []
            if res and 'entries' in res:
                for entry in res.get('entries', []):
                    if not entry: continue
                    results.append(TrackInfo(
                        identifier=str(entry.get('id', '')),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown'),
                        duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE))
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        mp3_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if mp3_path.exists() and mp3_path.stat().st_size > 20000:
            return DownloadResult(success=True, file_path=mp3_path, track_info=track_info)
        
        logger.info(f"[YT] Attempting Piped API download for {video_id}")
        result = await self._download_piped(video_id)
        
        if not result.success:
            logger.warning(f"[YT] Piped download failed. Falling back to yt-dlp minimal for {video_id}")
            result = await self._download_ytdlp_minimal(video_id)
        
        if result.success and result.file_path.suffix != ".mp3":
             logger.info(f"Downloaded non-mp3 file {result.file_path.name}, converting...")
             return await self._run_ffmpeg_postprocessor(result.file_path, track_info)

        return result

    async def _download_piped(self, video_id: str) -> DownloadResult:
        piped_instances = ["https://pipedapi.kavin.rocks", "https://pipedapi.moomoo.me", "https://pipedapi-libre.kavin.rocks", "https://pipedapi.smnz.de"]
        random.shuffle(piped_instances)

        async with httpx.AsyncClient(timeout=20.0) as client:
            for instance in piped_instances:
                try:
                    logger.info(f"Trying Piped instance: {instance} for {video_id}")
                    api_url = f"{instance}/streams/{video_id}"
                    info_resp = await client.get(api_url)
                    info_resp.raise_for_status()
                    data = info_resp.json()
                    
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams: continue

                    best_audio = max(audio_streams, key=lambda x: x.get("bitrate", 0))
                    audio_url = best_audio.get("url")
                    
                    if not audio_url: continue

                    file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.{best_audio.get('format', 'webm').lower()}"
                    
                    with file_path.open("wb") as f:
                        async with client.stream("GET", audio_url, timeout=60) as response:
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)
                    
                    if file_path.exists() and file_path.stat().st_size > 20000:
                        logger.info(f"Piped download successful from {instance}")
                        return DownloadResult(success=True, file_path=file_path)
                except Exception as e:
                    logger.warning(f"Piped instance {instance} failed: {e}")
                    continue
        return DownloadResult(success=False, error_message="All Piped instances failed")

    async def _download_ytdlp_minimal(self, video_id: str) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(self.ytdlp_fallback_opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception: return False
            
            success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=90.0)
            if success:
                return await self._wait_for_file(video_id)
        return DownloadResult(success=False, error_message="yt-dlp fallback failed")

    async def _run_ffmpeg_postprocessor(self, input_path: Path, track_info: Optional[TrackInfo]) -> DownloadResult:
        output_path = input_path.with_suffix(".mp3")
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', str(input_path), '-codec:a', 'libmp3lame', '-q:a', '2', str(output_path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            if proc.returncode == 0:
                input_path.unlink()
                return DownloadResult(success=True, file_path=output_path, track_info=track_info)
            return DownloadResult(success=False, error_message="FFmpeg conversion failed")
        except Exception: return DownloadResult(success=False, error_message="FFmpeg execution error")

    async def _wait_for_file(self, video_id: str) -> DownloadResult:
        start_wait = time.time()
        while time.time() - start_wait < 15:
            for ext in ['.mp3', '.webm', '.m4a', '.opus']:
                path = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
                if path.exists() and path.stat().st_size > 20000:
                    return DownloadResult(success=True, file_path=path)
            await asyncio.sleep(1)
        return DownloadResult(success=False, error_message="File not found after download")