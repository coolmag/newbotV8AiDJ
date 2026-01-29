import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import httpx
import yt_dlp
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v34 (Hybrid: Invidious API + SoundCloud + yt-dlp).
    Uses Invidious API for YouTube content, SoundCloud for fallback.
    yt-dlp is used for downloading via Invidious videoId and for SoundCloud.
    """
    
    # Список живых инстансов Invidious (2026)
    INVIDIOUS_INSTANCES = [
        "https://inv.tux.pro",
        "https://invidious.asir.dev",
        "https://inv.n8pjl.ca",
        "https://invidious.nerdvpn.de",
        "https://invidious.privacydev.net"
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(3)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """
        1. Ищем на Invidious (это YouTube контент).
        2. Если не вышло - ищем на SoundCloud.
        """
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"

        # --- Попытка 1: Invidious API ---
        inv_results = await self._search_invidious(query, limit)
        if inv_results:
            return inv_results
            
        # --- Попытка 2: SoundCloud (Резерв) ---
        logger.info("Invidious failed, switching to SoundCloud search...")
        return await self._search_soundcloud(query, limit)

    async def _search_invidious(self, query: str, limit: int) -> List[TrackInfo]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            random.shuffle(self.INVIDIOUS_INSTANCES)
            for instance in self.INVIDIOUS_INSTANCES:
                try:
                    logger.info(f"🔍 Searching on Invidious instance: {instance}")
                    resp = await client.get(
                        f"{instance}/api/v1/search", 
                        params={"q": query, "type": "video"},
                        headers=headers
                    )
                    if resp.status_code != 200: 
                        logger.warning(f"Invidious search on {instance} returned status {resp.status_code}")
                        continue
                    
                    data = resp.json()
                    results = []
                    for item in data[:limit]:
                        if item.get('lengthSeconds', 0) > 900: continue
                        
                        results.append(TrackInfo(
                            identifier=item.get('videoId'),
                            title=item.get('title'),
                            uploader=item.get('author'),
                            duration=item.get('lengthSeconds'),
                            thumbnail_url=item.get('videoThumbnails', [{}])[0].get('url'),
                            source="invidious"
                        ))
                    if results:
                        logger.info(f"✅ Search successful on {instance}")
                        return results
                except httpx.TimeoutException:
                    logger.warning(f"Invidious search on {instance} timed out.")
                    continue
                except httpx.RequestError as e:
                    logger.warning(f"Invidious search on {instance} failed: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Invidious search on {instance} encountered an unexpected error: {e}")
                    continue
        logger.error("All Invidious instances failed for search.")
        return []

    async def _search_soundcloud(self, query: str, limit: int) -> List[TrackInfo]:
        try:
            loop = asyncio.get_running_loop()
            opts = {'quiet': True, 'extract_flat': True, 'skip_download': True, 'ignoreerrors': True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"scsearch{limit}:{query}", download=False))
                
            results = []
            if info:
                for entry in info.get('entries', []):
                    if entry:
                        results.append(TrackInfo(
                            identifier=entry.get('url'),
                            title=entry.get('title'),
                            uploader=entry.get('uploader'),
                            duration=int(entry.get('duration', 0)),
                            source="soundcloud"
                        ))
            return results
        except Exception as e:
            logger.error(f"SoundCloud Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id[-10:]}.mp3" 
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            if track_info and track_info.source == "soundcloud":
                return await self._download_soundcloud(video_id, final_path, track_info)
            else:
                return await self._download_yt_dlp_from_id(video_id, final_path, track_info)

    async def _download_yt_dlp_from_id(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        logger.info(f"⬇️ Downloading via yt-dlp for ID: {video_id}")
        try:
            loop = asyncio.get_running_loop()
            temp_path = str(target_path).replace(".mp3", "_temp")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_path,
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                # Отключаем проверку сертификатов для yt-dlp (для обхода 526)
                'nocheckcertificate': True, 
            }
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(ydl_opts, f"https://www.youtube.com/watch?v={video_id}"))
            
            created_path = Path(temp_path + ".mp3")
            if created_path.exists() and created_path.stat().st_size > 10000:
                if created_path != target_path:
                    created_path.rename(target_path)
                logger.info(f"✅ Success via yt-dlp for ID: {video_id}")
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
        except Exception as e:
            logger.error(f"❌ yt-dlp download failed for ID {video_id}: {e}")
            pass
        return DownloadResult(success=False, error_message=f"yt-dlp download failed for ID {video_id}")


    async def _download_soundcloud(self, url: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        try:
            loop = asyncio.get_running_loop()
            temp_path = str(target_path).replace(".mp3", "")
            opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_path, 
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}],
            }
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(opts, url))
            
            created_path = Path(temp_path + ".mp3")
            if created_path.exists():
                if created_path != target_path:
                    created_path.rename(target_path)
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
        except Exception as e:
            logger.error(f"❌ SoundCloud download failed: {e}")
            pass
        return DownloadResult(success=False)

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
