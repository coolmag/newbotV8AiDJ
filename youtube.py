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
    ADAPTER: YOUTUBE RESURRECTED (2026 Edition)
    - Использует маскировку под Android Client для обхода PO Token.
    - Жесткие таймауты, чтобы бот не вис.
    - OAuth2 для авторизации (опционально, но рекомендуется).
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # ВАЖНО: Снижаем конкурентность. 5 потоков с одного IP = мгновенный бан от YouTube.
        # Лучше качать по 2 трека, но стабильно, чем 5 и получить бан.
        self.semaphore = asyncio.Semaphore(2) 
        self.search_semaphore = asyncio.Semaphore(2)

        self._url_cache: Dict[str, str] = {}
        
        # Опции "Анти-Блок"
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            
            # --- ГЛАВНЫЕ ФИШКИ ОБХОДА 2025-2026 ---
            
            # 1. Притворяемся Android-клиентом (он реже требует PO Token для аудио)
            # Варианты: 'android', 'web', 'ios'. Android сейчас самый стабильный для аудио.
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['hls', 'dash'], # Пропускаем потоковые форматы, которые часто троттлят
                }
            },
            
            # 2. Таймауты (чтобы бот не вис намертво)
            'socket_timeout': 15,
            'retries': 3,
            
            # 3. Анти-детект заголовки
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            },

            "postprocessors": [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            'nocheckcertificate': True,
            'ignoreerrors': True,
            
            # Если сервер забанен, раскомментируй строку ниже и используй прокси
            # 'proxy': 'http://user:pass@host:port', 
        }
        
        logger.info("🟢 YouTube Resurrected Engine initialized")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        """Поиск через ytsearch (возвращаемся к истокам)."""
        clean_query = query.lower().strip()
        
        # Добавляем "Audio" к запросу, чтобы yt-dlp искал музыку, а не клипы
        if "audio" not in clean_query and "lyrics" not in clean_query:
            search_text = f"{clean_query} audio"
        else:
            search_text = clean_query

        cache_key = f"yt_search_v2:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            
            def do_search():
                # Используем ytsearch вместо scsearch
                search_query = f"ytsearch{limit}:{search_text}"
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    try:
                        # flat_playlist=True ускоряет поиск в 10 раз (не получает полные данные видео сразу)
                        return ydl.extract_info(search_query, download=False)
                    except Exception as e:
                        logger.error(f"YT Search Error: {e}")
                        return None

            res = await loop.run_in_executor(None, do_search)
            
            results = []
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry: continue
                    
                    tid = str(entry.get('id', ''))
                    if not tid: continue
                    
                    # При flat_playlist duration может не быть, но это цена скорости
                    duration = int(entry.get('duration', 0))
                    
                    # Фильтр на "слишком длинные миксы" или "слишком короткие звуки"
                    # Если duration 0 (из-за flat поиска), пропускаем проверку
                    if duration > 0 and (duration < 45 or duration > 1200):
                        continue
                    
                    # Формируем полную ссылку сразу
                    url = f"https://www.youtube.com/watch?v={tid}"
                    self._url_cache[tid] = url

                    results.append(TrackInfo(
                        identifier=tid,
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown Artist'), # uploader -> channel
                        duration=duration,
                        source=Source.YOUTUBE,
                        thumbnail_url=entry.get('thumbnail', None)
                    ))

            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            
            logger.info(f"[YT] Search '{query}': {len(results)} tracks found")
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        video_id = str(video_id)
        
        # 1. Проверка кэша file_id (без изменений)
        file_id_cache_key = f"file_id:{video_id}"
        cached_file_id = await self._cache.get(file_id_cache_key)
        if cached_file_id:
            return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        # 2. Проверка файла (без изменений)
        for ext in ['.mp3', '.m4a', '.webm']: # ogg убрал, редкость
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
                    # Убеждаемся, что имя файла будет ID (важно для ffmpeg)
                    opts['outtmpl'] = str(self._settings.DOWNLOADS_DIR / f"{video_id}.%(ext)s")
                    
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"Download Error {video_id}: {e}")
                    return False

            success = await loop.run_in_executor(None, do_download)
            
            if not success:
                return DownloadResult(success=False, error_message="YT Download Failed", track_info=track_info)

            # 4. Ожидание файла (чуть уменьшил таймаут, 45 сек это долго)
            start_wait = time.time()
            while time.time() - start_wait < 30:
                for path in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"): # Точный поиск по ID
                    if path.is_file() and path.stat().st_size > 50000:
                        logger.info(f"[YT] Downloaded: {path.name}")
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                await asyncio.sleep(1)
            
            return DownloadResult(success=False, error_message="File lost after download", track_info=track_info)

    # ... остальные методы (cache_file_id, get_random...) без изменений ...