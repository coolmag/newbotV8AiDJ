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
    ADAPTER: RAILWAY SURVIVAL EDITION (2026) - Adapted
    Использует Nightly build yt-dlp + Android Client API + Cookies из COOKIES_CONTENT env.
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # --- RAILWAY MAGIC: Адаптировано под существующую переменную COOKIES_CONTENT ---
        self.cookies_path = Path("cookies/youtube_railway.txt")
        cookies_content = self._settings.COOKIES_CONTENT
        
        if cookies_content:
            try:
                self.cookies_path.parent.mkdir(exist_ok=True)
                # Важно: w+ запись, чтобы обновить если изменились
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies successfully loaded from Railway Env (COOKIES_CONTENT)!")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")
        else:
            logger.warning("⚠️ CRITICAL: No COOKIES_CONTENT variable found! Ban imminent.")

        # STRICT LIMITS: На Railway нельзя качать параллельно с одного IP
        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)
        
        self._url_cache: Dict[str, str] = {}

        # ОПЦИИ СМЕРТИ (Исправленная версия)
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            
            # ИЗМЕНЕНИЕ 1: Разрешаем любые форматы (yt-dlp сам разберется и сконвертирует)
            "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
            
            # 1. МАСКИРОВКА
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage", "configs", "js"],
                    # ИЗМЕНЕНИЕ 2: УБРАЛИ "skip": ["dash", "hls"] 
                    # Мы обязаны принимать DASH, иначе получаем "No format found"
                }
            },
            
            # 2. АНТИ-ФРИЗ
            "socket_timeout": 20,
            "retries": 10,
            
            # 3. АНТИ-БАН СКОРОСТИ
            "ratelimit": 2_500_000, # Чуть подняли лимит
            "sleep_interval": 2,
            
            # 4. ОБРАБОТКА (Конвертация в MP3)
            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True,
            'ignoreerrors': True,
        }
        
        # Подключаем куки
        if self.cookies_path.exists():
            self.ydl_opts['cookiefile'] = str(self.cookies_path)

        logger.info("🟢 YouTube Railway Survival Engine initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        """Поиск через ytsearch (быстрый)."""
        clean_query = query.lower().strip()
        if "audio" not in clean_query:
            search_text = f"{clean_query} audio"
        else:
            search_text = clean_query

        cache_key = f"yt_search_v4:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                opts = self.ydl_opts.copy()
                opts['extract_flat'] = True # Ускорение в 10 раз
                search_query = f"ytsearch{limit}:{search_text}"
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    try:
                        return ydl.extract_info(search_query, download=False)
                    except Exception as e:
                        logger.error(f"Search Error: {e}")
                        return None

            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=25.0)
            except asyncio.TimeoutError:
                return []
            
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry: continue
                    tid = str(entry.get('id', ''))
                    duration = int(entry.get('duration') or 0)
                    
                    if duration > 0 and (duration < 30 or duration > 1200):
                        continue
                        
                    results.append(TrackInfo(
                        identifier=tid,
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown'),
                        duration=duration,
                        source=Source.YOUTUBE,
                        thumbnail_url=None
                    ))

            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        video_id = str(video_id)
        
        # Проверки кэша и файлов (оставляем как есть)
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

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
                    opts = self.ydl_opts.copy()
                    opts['outtmpl'] = str(self._settings.DOWNLOADS_DIR / f"{video_id}.%(ext)s")
                    
                    # Пытаемся скачать
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    # Ловим специфичные ошибки
                    err_str = str(e).lower()
                    if "sign in" in err_str or "cookies" in err_str:
                        logger.critical("🚨 COOKIES EXPIRED OR INVALID! Update COOKIES_CONTENT.")
                    logger.error(f"Download Error {video_id}: {e}")
                    return False

            try:
                # 90 секунд на скачивание, потом обрыв
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=90.0)
            except asyncio.TimeoutError:
                return DownloadResult(success=False, error_message="Timeout (Ghosting)", track_info=track_info)
            
            if not success:
                return DownloadResult(success=False, error_message="Download Failed (Check Logs)", track_info=track_info)

            # Ждем появления файла
            start_wait = time.time()
            while time.time() - start_wait < 10:
                for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):
                    if path.is_file() and path.stat().st_size > 50000:
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                await asyncio.sleep(1)
            
            return DownloadResult(success=False, error_message="File lost after download", track_info=track_info)