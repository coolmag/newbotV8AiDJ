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
    ADAPTER: RAILWAY 'HYBRID' FINAL EDITION (2026)
    - Поиск с куками.
    - Скачивание без куков через "creator" клиенты.
    - Резервный метод скачивания через Invidious.
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

        # --- ОПЦИИ ДЛЯ ПОИСКА (с куками, т.к. это работает) ---
        self.search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 20,
            "retries": 3,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        }

        # --- ОПЦИИ ДЛЯ СКАЧИВАНИЯ (БЕЗ куков, через creator клиенты) ---
        self.download_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best[height<=480]/best",
            "ignore_no_formats_error": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android_creator", "web_creator"],
                }
            },
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "socket_timeout": 45,
            "retries": 5,
            'nocheckcertificate': True,
        }
        
        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            logger.info("Cookie file applied to SEARCH config.")

        logger.info("🟢 YouTube 'Hybrid' Engine initialized.")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        # ... (search logic is stable and remains the same)
        clean_query = query.lower().strip()
        if "audio" not in clean_query: search_text = f"{clean_query} audio"
        else: search_text = clean_query
        cache_key = f"yt_search_hybrid:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached
        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            def do_search():
                with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                    try:
                        return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception as e:
                        logger.error(f"Search Error: {e}", exc_info=True)
                        return None
            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=25.0)
            except asyncio.TimeoutError: return []
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry: continue
                    results.append(TrackInfo(
                        identifier=str(entry.get('id', '')),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown'),
                        duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE,
                        thumbnail_url=None))
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        for ext in ['.mp3', '.webm', '.m4a']:
            existing = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
            if existing.exists() and existing.stat().st_size > 50000:
                return DownloadResult(success=True, file_path=existing, track_info=track_info)

        # --- ГИБРИДНАЯ ЛОГИКА ---
        # 1. Пробуем стандартный метод (без куков, через creator client)
        logger.info(f"[YT] Attempting standard download for {video_id}")
        result = await self._download_standard(video_id, track_info)
        
        # 2. Если неудача, пробуем резервный метод через Invidious
        if not result.success:
            logger.warning(f"[YT] Standard download failed. Falling back to Invidious for {video_id}")
            result = await self._download_invidious(video_id, track_info)
        
        return result

    async def _download_standard(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    # "Simplest Patch" - последняя попытка прямого скачивания
                    opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "format": "251/250/worstaudio/worst",
                        "socket_timeout": 20,
                        "retries": 5,
                        "ignoreerrors": True,
                        "extractor_args": {"youtube": {"player_client": ["android_music"]}},
                        "http_headers": {
                            "User-Agent": "com.google.android.apps.youtube.music/6.21.51",
                        },
                        "postprocessors": [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        "outtmpl": str(self._settings.DOWNLOADS_DIR / f"{video_id}.%(ext)s"),
                        'nocheckcertificate': True,
                    }
                    
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Standard Download Error '{video_id}': {e}", exc_info=True)
                    return False
            try:
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=120.0)
            except asyncio.TimeoutError:
                return DownloadResult(success=False, error_message="Standard Download Timeout")
            
            if not success:
                return DownloadResult(success=False, error_message="Standard Download Failed")

            # Ожидание файла после конвертации
            return await self._wait_for_file(video_id)

    async def _download_invidious(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        # Список проверенных инстансов Invidious
        invidious_instances = ["https://invidious.fdn.fr", "https://inv.riverside.rocks", "https://yewtu.be", "https://invidious.nerdvpn.de"]
        random.shuffle(invidious_instances)
        
        file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"

        async with httpx.AsyncClient() as client:
            for instance in invidious_instances:
                try:
                    # itag=251 = opus@160k, itag=250 = opus@70k
                    audio_url = f"{instance}/latest_version?id={video_id}&itag=251&local=true"
                    logger.info(f"Trying Invidious instance: {instance} for {video_id}")
                    
                    with file_path.open("wb") as f:
                        async with client.stream("GET", audio_url, timeout=45) as response:
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)
                    
                    if file_path.exists() and file_path.stat().st_size > 20000:
                        logger.info(f"Invidious download successful from {instance}")
                        # Запускаем конвертацию в MP3, если скачался не MP3 (например, opus/webm)
                        return await self._run_ffmpeg_postprocessor(file_path, track_info)
                    else:
                        continue # Файл пустой, пробуем следующий инстанс
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    logger.warning(f"Invidious instance {instance} failed: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error with Invidious instance {instance}: {e}")
                    continue
        
        return DownloadResult(success=False, error_message="All Invidious instances failed")

    async def _run_ffmpeg_postprocessor(self, input_path: Path, track_info: Optional[TrackInfo]) -> DownloadResult:
        """Принудительно запускает FFmpeg для конвертации в MP3."""
        output_path = input_path.with_suffix(".mp3")
        if input_path == output_path:
            return DownloadResult(success=True, file_path=output_path, track_info=track_info)

        try:
            # Используем FFmpeg для конвертации
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', str(input_path), '-codec:a', 'libmp3lame', '-q:a', '2', str(output_path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"FFmpeg conversion failed: {stderr.decode()}")
                return DownloadResult(success=False, error_message="FFmpeg conversion failed")
            
            # Удаляем исходный файл
            input_path.unlink()
            return DownloadResult(success=True, file_path=output_path, track_info=track_info)
        except Exception as e:
            logger.error(f"FFmpeg execution error: {e}")
            return DownloadResult(success=False, error_message="FFmpeg execution error")

    async def _wait_for_file(self, video_id: str) -> DownloadResult:
        start_wait = time.time()
        while time.time() - start_wait < 20:
            # Приоритет на MP3 после конвертации
            mp3_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if mp3_path.exists() and mp3_path.stat().st_size > 50000:
                return DownloadResult(success=True, file_path=mp3_path)
            
            # Fallback на любой другой скачанный файл
            for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):
                if path.is_file() and path.stat().st_size > 50000:
                    return DownloadResult(success=True, file_path=path)
            
            await asyncio.sleep(1)
        return DownloadResult(success=False, error_message="File not found after download")