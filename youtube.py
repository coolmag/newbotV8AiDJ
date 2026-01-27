import asyncio
import logging
import random
import os
import json
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
    Titanium Downloader Architecture (2026).
    Priority: Cobalt API -> Piped API -> Direct yt-dlp
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.cookies_path = Path("cookies.txt")
        if self._settings.COOKIES_CONTENT:
            try:
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(self._settings.COOKIES_CONTENT)
            except: pass

        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        # Легкие настройки поиска
        self.search_opts = {
            'quiet': True, 
            'extract_flat': True, 
            'skip_download': True, 
            'ignoreerrors': True, 
            'nocheckcertificate': True
        }

        logger.info("🛡 Titanium YouTube Engine: Delegated Downloading Active.")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        cache_key = f"yt_search_v3:{query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
            
            results = []
            if info:
                entries = info.get('entries', []) if 'entries' in info else [info]
                for entry in entries:
                    if not entry or entry.get('duration', 0) > 1200: continue
                    results.append(TrackInfo(
                        identifier=entry.get('id'),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('uploader') or entry.get('channel', 'Unknown'),
                        duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE
                    ))
            
            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown", artist="Unknown", duration=0)

        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            res = await self._try_cobalt(video_id, track_info)
            if not res.success: res = await self._try_piped(video_id, track_info)
            if not res.success: res = await self._try_direct(video_id, track_info)
            
            return await self._post_process(res)

    async def _try_cobalt(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        logger.info(f"🧬 [Cobalt] Attempting {video_id}...")
        
        instances = self._settings.COBALT_INSTANCES or []
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=40.0, verify=False) as client:
            for base_url in instances:
                try:
                    payload = {"url": f"https://www.youtube.com/watch?v={video_id}", "aFormat": "mp3", "isAudioOnly": True}
                    resp = await client.post(f"{base_url}/api/json", json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"})
                    
                    if resp.status_code not in [200, 201]: continue
                    dl_url = resp.json().get("url")
                    if not dl_url: continue
                    
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_cobalt.mp3"
                    async with client.stream("GET", dl_url) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                                
                    if temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Cobalt] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                except Exception: continue
        return DownloadResult(success=False, error_message="Cobalt failed")

    async def _try_piped(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        logger.info(f"🧪 [Piped] Attempting {video_id}...")
        
        instances = self._settings.PIPED_INSTANCES or []
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
            for base_url in instances:
                try:
                    resp = await client.get(f"{base_url}/streams/{video_id}")
                    if resp.status_code != 200: continue
                    streams = resp.json().get("audioStreams", [])
                    if not streams: continue
                    
                    dl_url = max(streams, key=lambda x: x.get("bitrate", 0)).get("url")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_piped.m4a"
                    
                    async with client.stream("GET", dl_url) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                                
                    if temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Piped] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                except Exception: continue
        return DownloadResult(success=False, error_message="Piped failed")

    async def _try_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        logger.warning(f"⚠️ [Direct] Attempting fallback for {video_id}...")
        url = f"https://www.youtube.com/watch?v={video_id}"
        opts = {'format': 'bestaudio/best', 'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"), 'quiet': True, 'no_warnings': True, 'nocheckcertificate': True, 'extractor_args': {'youtube': {'player_client': ['android', 'ios'], 'player_skip': ['webpage', 'configs']}}}
        if self.cookies_path.exists(): opts['cookiefile'] = str(self.cookies_path)
        try:
            loop = asyncio.get_running_loop()
            with yt_dlp.YoutubeDL(opts) as ydl: await loop.run_in_executor(None, lambda: ydl.download([url]))
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                if f.stat().st_size > 10000: return DownloadResult(success=True, file_path=f, track_info=track_info)
        except Exception as e: logger.error(f"[Direct] Failed: {e}")
        return DownloadResult(success=False, error_message="Direct failed")

    async def _post_process(self, result: DownloadResult) -> DownloadResult:
        if not result.success or not result.file_path: return result
        target = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        if result.file_path.suffix == ".mp3" and result.file_path.name == target.name: return result
        try:
            proc = await asyncio.create_subprocess_exec('ffmpeg', '-y', '-i', str(result.file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(target), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
            if target.exists() and target.stat().st_size > 0:
                try: result.file_path.unlink() 
                except: pass
                result.file_path = target
        except Exception as e: logger.error(f"FFmpeg error: {e}")
        return result