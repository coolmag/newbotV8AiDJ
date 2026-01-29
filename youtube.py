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
    ☁️ SoundCloud Downloader (Adapter).
    Replaces YouTube logic with SoundCloud.
    Works perfectly on Railway/Hosting IPs.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        # SoundCloud лоялен, можно качать в 2-3 потока
        self.semaphore = asyncio.Semaphore(3)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Поиск треков на SoundCloud"""
        
        # Если радио передает 'decade' (годы), добавляем в запрос
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
            
        # Используем префикс 'scsearch' вместо 'ytsearch'
        search_query = f"scsearch{limit}:{query}"
        
        opts = {
            'quiet': True,
            'extract_flat': True, # Быстрый поиск без метаданных
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
                    # На SoundCloud нет "видео", там треки.
                    # Но мы фильтруем слишком длинные сеты (> 20 минут)
                    if entry.get('duration') and entry.get('duration') > 1200:
                        continue
                        
                    # Важно: yt-dlp возвращает id как цифры для SC, 
                    # но лучше использовать 'url' или 'webpage_url' как идентификатор
                    if entry:
                        # Адаптируем под структуру TrackInfo
                        # TrackInfo ожидает id, title, channel_title (uploader), duration
                        track = TrackInfo(
                            identifier=entry.get('url'), # Сохраняем полную ссылку как ID
                            title=entry.get('title', 'Unknown Track'),
                            uploader=entry.get('uploader', 'SoundCloud Artist'),
                            duration=int(entry.get('duration', 0)),
                            thumbnail_url=entry.get('thumbnail') or entry.get('thumbnails', [{}])[-1].get('url'),
                            source="soundcloud" # Помечаем источник
                        )
                        results.append(track)
            return results
        except Exception as e:
            logger.error(f"SoundCloud Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """
        Скачивание с SoundCloud.
        video_id здесь будет полной ссылкой (URL), так как мы сохранили её в search.
        """
        
        # Генерируем имя файла из URL (чтобы было безопасно для ФС)
        # SoundCloud ссылки длинные, сделаем хэш или возьмем последнюю часть
        safe_filename = video_id.split('/')[-1] if '/' in video_id else video_id
        if len(safe_filename) > 50: safe_filename = safe_filename[-50:]
        
        final_path = self._settings.DOWNLOADS_DIR / f"{safe_filename}.mp3"
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            logger.info(f"✅ Cache hit for {safe_filename}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"☁️ Downloading from SoundCloud: {safe_filename}...")
            return await self._download_direct(video_id, final_path, track_info)

    async def _download_direct(self, url: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        # Временный файл
        temp_path = str(target_path).replace(".mp3", "_temp")
        
        ydl_opts = {
            'format': 'bestaudio/best', # SoundCloud отдает mp3 или opus
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
            
            # Конвертируем всё в MP3 для совместимости с Telegram
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        try:
            loop = asyncio.get_running_loop()
            # Передаем URL напрямую
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, url))
            
            # yt-dlp добавляет расширение .mp3 автоматически
            mp3_temp_path = Path(f"{temp_path}.mp3")
            
            if mp3_temp_path.exists() and mp3_temp_path.stat().st_size > 10000:
                # Переименовываем в итоговый файл
                if mp3_temp_path != target_path:
                    mp3_temp_path.rename(target_path)
                
                logger.info(f"✅ Download success: {url}")
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            else:
                return DownloadResult(success=False, error_message="File too small or missing")

        except Exception as e:
            logger.error(f"❌ SoundCloud download failed: {e}")
            return DownloadResult(success=False, error_message=str(e))

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
