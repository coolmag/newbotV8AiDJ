import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import httpx
import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v20 (Cobalt Resurrection).
    Strategy: Exclusive use of Cobalt API v10 with aggressive failover.
    Direct download is disabled as Railway IPs are hard-banned.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        logger.info(f"🛡️ Titanium v20 (Cobalt Only). Instances: {len(self._settings.COBALT_INSTANCES)}")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        # Search still works directly because metadata APIs are less strict
        cache_key = f"yt_search_v11:{query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        opts = {'quiet': True, 'extract_flat': True, 'skip_download': True, 'ignoreerrors': True}
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
            
            results = []
            if info:
                entries = info.get('entries', []) if 'entries' in info else [info]
                for entry in entries:
                    if not entry or int(entry.get('duration') or 0) > 1200: continue
                    results.append(TrackInfo(
                        identifier=entry.get('id'),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('uploader') or entry.get('channel', 'Unknown'),
                        duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE
                    ))
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown", artist="Unknown", duration=0, source=Source.YOUTUBE)

        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            logger.info(f"📁 Cache hit: {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            # === COBALT STRATEGY ===
            logger.info(f"🔷 Trying Cobalt API chain for {video_id}...")
            res = await self._try_cobalt_chain(video_id, track_info)
            if res.success: return await self._post_process(res)
            
            return DownloadResult(success=False, error_message="Cobalt failed", track_info=track_info)

    async def _try_cobalt_chain(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        instances = list(self._settings.COBALT_INSTANCES or [])
        random.shuffle(instances)
        
        # Headers mimicking a browser to avoid jwt.missing on some instances
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://cobalt.tools",
            "Referer": "https://cobalt.tools/"
        }

        for base_url in instances:
            try:
                async with httpx.AsyncClient(timeout=45.0, verify=False, follow_redirects=True) as client:
                    # COBALT v10 PAYLOAD
                    payload = {
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "downloadMode": "audio",
                        "audioFormat": "mp3",
                        "videoQuality": "144"
                    }
                    
                    # Try ROOT endpoint (v10 standard)
                    resp = await client.post(base_url, json=payload, headers=headers)
                    
                    # If 404, try /api/json (v7 standard)
                    if resp.status_code == 404:
                        resp = await client.post(f"{base_url}/api/json", json=payload, headers=headers)

                    if resp.status_code not in (200, 201):
                        # logger.warning(f"   ⚠️ {base_url} -> {resp.status_code}")
                        continue
                    
                    data = resp.json()
                    
                    # Parse response
                    dl_url = None
                    if data.get("url"): dl_url = data.get("url")
                    elif data.get("audio"): dl_url = data.get("audio")
                    elif data.get("picker"): dl_url = data["picker"][0].get("url")
                    
                    if not dl_url: continue
                    
                    # Download file
                    logger.info(f"   ⬇️ Downloading from {base_url}...")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_cobalt.mp3"
                    async with client.stream("GET", dl_url, timeout=120.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192): f.write(chunk)
                            
                    if temp_path.stat().st_size > 10000:
                        logger.info(f"✅ Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
            except Exception: continue
            
        return DownloadResult(success=False)

    async def _post_process(self, result: DownloadResult) -> DownloadResult:
        if not result.success or not result.file_path: return result
        target = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        if result.file_path == target: return result
        try:
            # Simple move if already MP3, else convert
            if result.file_path.suffix == ".mp3":
                result.file_path.rename(target)
                result.file_path = target
            else:
                proc = await asyncio.create_subprocess_exec('ffmpeg', '-y', '-i', str(result.file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(target), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(proc.wait(), timeout=120)
                if target.exists():
                    try: result.file_path.unlink()
                    except: pass
                    result.file_path = target
        except Exception: pass
        return result
