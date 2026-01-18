from __future__ import annotations
import asyncio
import logging
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:

    """

    ADAPTER: YOUTUBE HYBRID (v2) - Railway Edition

    - Reads cookies from COOKIES_CONTENT env var.

    - Enhanced logging for search diagnostics.

    """

    def __init__(self, settings: Settings, cache_service: CacheService):

        self._settings = settings

        self._cache = cache_service

        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)

        

        # Снижаем нагрузку. 2 потока — потолок для облачных IP.

        self.semaphore = asyncio.Semaphore(2)

        self.search_semaphore = asyncio.Semaphore(2)

        

        self._url_cache: Dict[str, str] = {}



        self.ydl_opts = {

            "quiet": True,

            "no_warnings": True,

            # Важно! Формат bestaudio часто лучше чем конкретный mp3 для скорости

            "format": "bestaudio/best",

            

            # --- ГЛАВНЫЙ ФИКС ЗАВИСАНИЙ ---

            "socket_timeout": 15,        # Если нет ответа 15 сек — обрыв

            "retries": 5,                # Пробуем 5 раз

            "fragment_retries": 5,       # Если кусок видео не скачался

            

            # --- ГЛАВНЫЙ ФИКС БЛОКИРОВОК (Android Client) ---

            "extractor_args": {

                "youtube": {

                    # Притворяемся Android-приложением (самый живучий метод сейчас)

                    "player_client": ["android", "web"],

                    "player_skip": ["webpage", "configs", "js"],

                    "skip": ["dash", "hls"], # Пропуск потоковых форматов (часто виснут)

                }

            },

            

            # --- АНТИ-ДЕТЕКТ ЗАГОЛОВКИ (Как у Android телефона) ---

            "http_headers": {

                "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36",

                "Accept-Language": "en-US,en;q=0.9",

            },



            "postprocessors": [{

                'key': 'FFmpegExtractAudio',

                'preferredcodec': 'mp3',

                'preferredquality': '192',

            }],

            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),

            'nocheckcertificate': True,

            'ignoreerrors': True,

        }

        

        # --- RAILWAY COOKIE INTEGRATION ---

        if self._settings.COOKIES_CONTENT:

            try:

                # Write the content from the env var to the file specified in config

                self._settings.COOKIES_FILE.write_text(self._settings.COOKIES_CONTENT)

                self.ydl_opts['cookiefile'] = str(self._settings.COOKIES_FILE)

                logger.info("🍪 Cookies successfully loaded from environment variable.")

            except Exception as e:

                logger.error(f"Failed to write cookies from env var to file: {e}")

        else:

            logger.warning("⚠️ COOKIES_CONTENT env var is not set. Running without cookies.")



        logger.info("🟢 YouTube Hybrid Engine (v2) initialized")



    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:

        """Быстрый поиск через ytsearch с таймаутом и улучшенным логированием."""

        clean_query = query.lower().strip()

        

        # Хак: добавляем "audio", если ищем не клип

        if "audio" not in clean_query and "lyrics" not in clean_query:

            search_text = f"{clean_query} audio"

        else:

            search_text = clean_query



        cache_key = f"yt_search_v3:{clean_query}"

        cached = await self._cache.get(cache_key)

        if cached:

            logger.info(f"[YT Search] Cache HIT for query: '{query}'")

            return cached



        async with self.search_semaphore:

            loop = asyncio.get_running_loop()

            

            def do_search():

                # ytsearchN: возвращает N результатов

                search_query = f"ytsearch{limit}:{search_text}"

                

                # Копируем опции и включаем flat_playlist для скорости (не качаем данные видео)

                opts = self.ydl_opts.copy()

                opts['extract_flat'] = True 

                

                with yt_dlp.YoutubeDL(opts) as ydl:

                    try:

                        return ydl.extract_info(search_query, download=False)

                    except Exception as e:

                        # Log the specific yt-dlp error

                        logger.error(f"[YT Search] Downloader exception for query '{query}': {e}", exc_info=True)

                        return None



            try:

                # Обертка в wait_for, чтобы поиск не вешал бота

                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=20.0)

            except asyncio.TimeoutError:

                logger.error(f"[YT Search] TIMEOUT for query: '{query}'")

                return []

            

            if not res or 'entries' not in res or not res['entries']:

                logger.warning(f"[YT Search] FAILED or NO RESULTS for query: '{query}'.")

                return []



            results = []

            for entry in res['entries']:

                if not entry: continue

                

                tid = str(entry.get('id', ''))

                title = entry.get('title', 'Unknown')

                

                # При extract_flat=True длительность иногда может быть None

                duration = int(entry.get('duration') or 0)

                

                # Базовая фильтрация мусора

                if duration > 0 and (duration < 30 or duration > 1200):

                    continue

                    

                results.append(TrackInfo(

                    identifier=tid,

                    title=title,

                    artist=entry.get('channel', 'Unknown'), # uploader -> channel

                    duration=duration,

                    source=Source.YOUTUBE,

                    thumbnail_url=None # При flat поиске тамбнейла может не быть сразу

                ))



            if results:

                logger.info(f"[YT Search] Success. Found {len(results)} tracks for query: '{query}'")

                await self._cache.set(cache_key, results, ttl=3600)

            else:

                # This case is hit if all entries were filtered out

                logger.warning(f"[YT Search] Found entries for '{query}', but all were filtered out (e.g., by duration).")



            return results



    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:

        video_id = str(video_id)

        

        # 1. Кэш ID

        file_id_cache_key = f"file_id:{video_id}"

        cached_file_id = await self._cache.get(file_id_cache_key)

        if cached_file_id:

            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)



        # 2. Файл на диске

        for ext in ['.mp3', '.m4a', '.webm']:

            existing = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"

            if existing.exists() and existing.stat().st_size > 50000:

                return DownloadResult(success=True, file_path=existing, track_info=track_info)



        url = f"https://www.youtube.com/watch?v={video_id}"



        async with self.semaphore:

            logger.info(f"[YT] Downloading: {video_id}")

            loop = asyncio.get_running_loop()

            

            def do_download():

                try:

                    # Важно: создаем новый экземпляр опций для каждого скачивания

                    opts = self.ydl_opts.copy()

                    opts['outtmpl'] = str(self._settings.DOWNLOADS_DIR / f"{video_id}.%(ext)s")

                    

                    with yt_dlp.YoutubeDL(opts) as ydl:

                        ydl.download([url])

                    return True

                except Exception as e:

                    logger.error(f"Download Error {video_id}: {e}")

                    return False



            try:

                # Ждем скачивания максимум 60 секунд, иначе убиваем процесс

                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=60.0)

            except asyncio.TimeoutError:

                logger.error(f"Download TIMEOUT for {video_id}")

                return DownloadResult(success=False, error_message="Download timed out (ghosting)", track_info=track_info)

            

            if not success:

                return DownloadResult(success=False, error_message="Download Failed", track_info=track_info)



            # 4. Проверка результата

            start_wait = time.time()

            while time.time() - start_wait < 10: # Ждем конвертации FFmpeg

                for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):

                    if path.is_file() and path.stat().st_size > 50000:

                        return DownloadResult(success=True, file_path=path, track_info=track_info)

                await asyncio.sleep(1)

            

            return DownloadResult(success=False, error_message="File lost", track_info=track_info)
