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
    🎵 YouTube Music Edition (v41 - JS Runtime Fix).
    Strategy: Explicitly tell yt-dlp to use the available 'node' JS runtime.
    This is an attempt to fix 'Signature solving failed' and related issues.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(1)
        self.ytmusic = YTMusic() 

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
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
                duration_text = item.get('duration', '0:00')
                try:
                    parts = duration_text.split(':')
                    duration = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(parts[0])
                except (ValueError, TypeError):
                    duration = 0
                if duration > 900: continue
                track = TrackInfo(
                    identifier=video_id,
                    title=item.get('title'),
                    artist=artists,
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
            await asyncio.sleep(random.uniform(2, 5))
            logger.info(f"🎧 Downloading {video_id} (YTM Web Mode)...")
            return await self._download_direct(video_id, final_path, track_info)

    async def _download_direct(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        temp_path = str(target_path).replace(".mp3", "_temp")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'js_runtimes': 'node', # Explicitly use node
            'extractor_args': {
                'youtube': {
                    'player_client': ['WEB_REMIX'],
                }
            },
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        }
        try:
            loop = asyncio.get_running_loop()
            url = f"https://music.youtube.com/watch?v={video_id}"
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, url))
            result_path = Path(temp_path + ".mp3")
            if not result_path.exists(): result_path = Path(temp_path)
            if result_path.exists() and result_path.stat().st_size > 10000:
                if result_path != target_path:
                    if target_path.exists(): target_path.unlink()
                    result_path.rename(target_path)
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            else:
                logger.warning(f"YTM Web client failed for {video_id}, retrying with fallback...")
                return await self._download_fallback(video_id, target_path, track_info)
        except Exception as e:
            logger.error(f"❌ Download error (YTM Web Client): {e}")
            logger.warning(f"Trying fallback for {video_id} after error.")
            return await self._download_fallback(video_id, target_path, track_info)

    async def _download_fallback(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Запасной вариант: стандартный веб-клиент yt-dlp с JS"""
        temp_path = str(target_path).replace(".mp3", "_temp_fb")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_path,
            'quiet': True,
            'nocheckcertificate': True,
            'js_runtimes': 'node', # Explicitly use node
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}],
        }
        try:
            logger.info(f".... Trying fallback download for {video_id} (default web client with JS)")
            loop = asyncio.get_running_loop()
            url = f"https://www.youtube.com/watch?v={video_id}"
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, url))
            result_path = Path(temp_path + ".mp3")
            if result_path.exists() and result_path.stat().st_size > 10000:
                if target_path.exists(): target_path.unlink()
                result_path.rename(target_path)
                logger.info(f"✅ Success via Fallback for {video_id}")
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
        except Exception as e:
            logger.error(f"❌ Fallback download error: {e}")
        logger.error(f"All download methods failed for {video_id}")
        return DownloadResult(success=False, error_message="All download methods failed")

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
