import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import yt_dlp
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ☁️ SoundCloud Only (v33 Stable).
    Полный отказ от YouTube/Piped из-за блокировок сети Railway.
    Работает исключительно с SoundCloud.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        # SoundCloud не банит за скорость, можно 4 потока
        self.semaphore = asyncio.Semaphore(4)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """
        Поиск только по SoundCloud.
        Использует префикс 'scsearch:' для yt-dlp.
        """
        
        # Если радио модуль передает года (например, "2000s"), добавляем в запрос
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
            
        logger.info(f"🔎 SoundCloud Search: {query}")
        
        # scsearch10:query - искать 10 треков
        search_query = f"scsearch{limit}:{query}"
        
        opts = {
            'quiet': True,
            'extract_flat': True, # Максимально быстрый поиск (без метаданных потоков)
            'skip_download': True,
            'ignoreerrors': True,
            'noplaylist': True,
        }
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
            
            results = []
            if info:
                entries = info.get('entries', [])
                for entry in entries:
                    # Фильтруем сеты длиннее 20 минут (1200 сек), чтобы не забивать память
                    if entry.get('duration') and entry.get('duration') > 1200:
                        continue
                        
                    if entry:
                        track = TrackInfo(
                            identifier=entry.get('url'), # Для SC идентификатор — это URL
                            title=entry.get('title', 'Unknown Track'),
                            uploader=entry.get('uploader', 'SoundCloud Artist'),
                            duration=int(entry.get('duration', 0)),
                            thumbnail_url=entry.get('thumbnail'),
                            source="soundcloud" # Важная метка
                        )
                        results.append(track)
            
            logger.info(f"✅ Found {len(results)} tracks on SoundCloud")
            return results
        except Exception as e:
            logger.error(f"❌ SoundCloud Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """
        Скачивание трека с SoundCloud.
        video_id здесь — это полный URL трека.
        """
        
        # Делаем безопасное имя файла из URL
        safe_name = video_id.split('/')[-1] if '/' in video_id else video_id
        # Обрезаем, если слишком длинное
        safe_name = safe_name[:50]
        
        final_path = self._settings.DOWNLOADS_DIR / f"{safe_name}.mp3"
        
        # Проверка кэша
        if final_path.exists() and final_path.stat().st_size > 10000:
            logger.info(f"✅ Cache hit for {safe_name}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"☁️ Downloading from SoundCloud: {safe_name}...")
            return await self._download_direct(video_id, final_path, track_info)

    async def _download_direct(self, url: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        # Временный файл
        temp_path = str(target_path).replace(".mp3", "_temp")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
            # Для SoundCloud не нужны куки и юзер-агенты, он открытый
            
            # Конвертируем в MP3, так как SC иногда отдает Opus/Ogg
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, url))
            
            # yt-dlp мог добавить .mp3 к имени файла
            result_path = Path(temp_path + ".mp3")
            
            # Если файл не создался с .mp3, проверяем без расширения (редко)
            if not result_path.exists():
                result_path = Path(temp_path)

            if result_path.exists() and result_path.stat().st_size > 10000:
                # Переименовываем в финальный путь
                if result_path != target_path:
                    result_path.rename(target_path)
                
                logger.info(f"✅ Download success: {url}")
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            else:
                logger.error(f"File missing after download: {result_path}")
                return DownloadResult(success=False, error_message="File missing")

        except Exception as e:
            logger.error(f"❌ SoundCloud download failed: {e}")
            return DownloadResult(success=False, error_message=str(e))

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])