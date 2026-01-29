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
    🛡️ Titanium Downloader v22.1 (Fix: Added **kwargs support).
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(2)

    # 👇 ИСПРАВЛЕНИЕ: Добавил **kwargs, чтобы не падало при вызове из radio.py
    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        # Если передан параметр 'decade' (десятилетие), добавляем его в запрос
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
            
        opts = {
            'quiet': True,
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Используем query с добавленным десятилетием
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch{limit}:{query}", download=False))
            
            results = []
            if info:
                entries = info.get('entries', [])
                for entry in entries:
                    if entry and entry.get('id'):
                        results.append(TrackInfo.from_yt_info(entry))
            return results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"🛡️ Starting stealth download for {video_id}...")
            return await self._download_direct(video_id, track_info)

    async def _download_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_temp"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(temp_path),
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'cookiefile': 'cookies.txt', # Не забудь загрузить cookies.txt!
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'player_skip': ['webpage', 'configs', 'js'],
                }
            },
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, video_id))
            
            mp3_path = Path(f"{str(temp_path)}.mp3")
            
            if mp3_path.exists() and mp3_path.stat().st_size > 10000:
                logger.info(f"✅ Download success: {video_id}")
                target_path = self._settings.DOWNLOADS_DIR / f"{track_info.identifier}.mp3" if track_info else mp3_path
                if mp3_path != target_path:
                    mp3_path.rename(target_path)
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            else:
                return DownloadResult(success=False, error_message="File too small or missing")

        except Exception as e:
            logger.error(f"❌ Download failed for {video_id}: {e}")
            return DownloadResult(success=False, error_message=str(e))

    def _run_yt_dlp(self, opts, video_id):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])