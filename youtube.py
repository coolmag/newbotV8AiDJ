import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import httpx
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v33 (Pure Piped API with Smart Retry).
    Bypasses YouTube IP blocks by using Piped instances as proxies.
    No yt-dlp dependencies for network operations.
    """
    
    # Список инстансов Piped. 
    PIPED_INSTANCES = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.rivo.df7.re",
        "https://pipedapi.lunar.icu",
        "https://pipedapi.ramat.org",
        "https://api.piped.projectsegfau.lt"
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(3)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Поиск через Piped API (без yt-dlp) с умным перебором."""
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"

        # Перемешиваем список, чтобы не долбить один и тот же сервер
        instances = self.PIPED_INSTANCES.copy()
        random.shuffle(instances)

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client: # verify=False для обхода SSL ошибок
            for instance in instances:
                try:
                    logger.info(f"🔍 Searching on Piped instance: {instance}")
                    resp = await client.get(f"{instance}/search", params={"q": query, "filter": "music_songs"})
                    
                    if resp.status_code != 200:
                        logger.warning(f"Piped search on {instance} returned status {resp.status_code}")
                        continue
                    
                    data = resp.json()
                    items = data.get('items', [])
                    results = []
                    
                    for item in items[:limit]:
                        vid_url = item.get('url', '')
                        vid_id = vid_url.split('v=')[-1] if 'v=' in vid_url else ''
                        
                        if not vid_id: continue
                        if item.get('duration', 0) > 900: continue # Фильтр 15 мин

                        track = TrackInfo(
                            identifier=vid_id,
                            title=item.get('title'),
                            uploader=item.get('uploaderName'),
                            duration=item.get('duration', 0),
                            thumbnail_url=item.get('thumbnail'),
                            source="piped"
                        )
                        results.append(track)
                    
                    if results:
                        logger.info(f"✅ Search successful on {instance}")
                        return results # Если нашли на одном инстансе, возвращаем
                        
                except httpx.TimeoutException:
                    logger.warning(f"Piped search on {instance} timed out.")
                    continue
                except httpx.RequestError as e:
                    logger.warning(f"Piped search on {instance} failed: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Piped search on {instance} encountered an unexpected error: {e}")
                    continue
        
        logger.error("All Piped instances failed for search.")
        return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            return await self._download_piped(video_id, final_path, track_info)

    async def _download_piped(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Скачивание аудиопотока через Piped с умным перебором"""
        
        instances = self.PIPED_INSTANCES.copy()
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, verify=False) as client: # verify=False для обхода SSL ошибок
            for instance in instances:
                try:
                    logger.info(f"🧪 Trying Piped Instance: {instance} for {video_id}")
                    
                    resp = await client.get(f"{instance}/streams/{video_id}")
                    if resp.status_code != 200: 
                        logger.warning(f"Instance {instance} returned {resp.status_code}")
                        continue
                        
                    data = resp.json()
                    audio_streams = data.get('audioStreams', [])
                    
                    if not audio_streams:
                        logger.warning(f"No audio streams on {instance}")
                        continue
                        
                    best_stream = sorted(audio_streams, key=lambda x: x.get('bitrate', 0), reverse=True)[0]
                    stream_url = best_stream.get('url')
                    
                    if not stream_url: continue

                    logger.info(f"⬇️ Downloading stream from {instance}...")
                    
                    temp_path = str(target_path).replace(".mp3", "_temp")
                    
                    async with client.stream("GET", stream_url) as stream_resp:
                        if stream_resp.status_code == 200:
                            with open(temp_path, "wb") as f:
                                async for chunk in stream_resp.aiter_bytes(chunk_size=8192):
                                    f.write(chunk)
                                    
                    temp_file = Path(temp_path)
                    if temp_file.exists() and temp_file.stat().st_size > 10000:
                        if temp_file != target_path:
                            temp_file.rename(target_path)
                        
                        logger.info(f"✅ Success via Piped: {instance}")
                        return DownloadResult(success=True, file_path=target_path, track_info=track_info)
                    
                except httpx.TimeoutException:
                    logger.warning(f"Piped download on {instance} timed out.")
                    continue
                except httpx.RequestError as e:
                    logger.warning(f"Piped download on {instance} failed: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Piped download on {instance} encountered an unexpected error: {e}")
                    continue

        logger.error("All Piped instances failed for download.")
        return DownloadResult(success=False, error_message="All Piped instances failed.")