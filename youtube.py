import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import yt_dlp
from ytmusicapi import YTMusic
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🎵 YouTube Music Edition (v37 Final Fix).
    Fixes:
    1. Reverted 'author' -> 'uploader' to match models.py.
    2. Uses 'tv_embedded' client for downloads (anti-ban).
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(1)
        self.ytmusic = YTMusic() 

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Поиск через YouTube Music API"""
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
            
        if not query or not query.strip(): return []
            
        logger.info(f"🔎 YTMusic Search: {query}")
        
        loop = asyncio.get_running_loop()
        try:
            search_results = await loop.run_in_executor(None, lambda: self.ytmusic.search(query, filter="songs", limit=limit))
            
            results = []
            for item in search_results:
                video_id = item.get('videoId')
                if not video_id: continue
                
                artists = ", ".join([a['name'] for a in item.get('artists', [])])
                
                # Парсинг длительности
                duration_text = item.get('duration', '0:00')
                try:
                    parts = duration_text.split(':')
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    else:
                        duration = int(parts[0])
                except ValueError: # Added ValueError for robustness
                    duration = 0
                
                if duration > 900: continue

                # 👇 ИСПРАВЛЕНО: Вернули uploader
                track = TrackInfo(
                    identifier=video_id,
                    title=item.get('title'),
                    uploader=artists,  # <--- ВЕРНУЛИ КАК БЫЛО
                    duration=duration,
                    thumbnail_url=item.get('thumbnails', [{}])[-1].get('url'),
                    source="ytmusic"
                )
                results.append(track)
            
            logger.info(f"✅ Found {len(results)} tracks on YTMusic")
            return results

        except Exception as e:
            logger.error(f"❌ YTMusic Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            logger.info(f"✅ Cache hit for {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            wait_time = random.randint(5, 12)
            await asyncio.sleep(wait_time)
            logger.info(f"📺 Downloading {video_id} (TV Mode)...")
            return await self._download_direct(video_id, final_path, track_info)

    async def _download_direct(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        temp_path = str(target_path).replace(".mp3", "_temp")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded', 'ios'], # TV режим от бана
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
            url = f"https://music.youtube.com/watch?v={video_id}"
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, url))
            
            result_path = Path(temp_path + ".mp3")
            if not result_path.exists():
                 # yt-dlp might sometimes not add .mp3 extension if the format is already mp3
                 result_path = Path(temp_path)

            if result_path.exists() and result_path.stat().st_size > 10000:
                if result_path != target_path:
                    # Ensure the final path is correct if yt-dlp saved it differently
                    if target_path.exists():
                        target_path.unlink() # Delete if already exists to avoid OSError
                    result_path.rename(target_path)
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            else:
                return DownloadResult(success=False, error_message="Download failed")

        except Exception as e:
            logger.error(f"❌ Download error: {e}")
            return DownloadResult(success=False, error_message=str(e))

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])