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
    Titanium Downloader v2 (Debug Edition).
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

        logger.info(f"🛡 Titanium Engine Active. Loaded {len(self._settings.COBALT_INSTANCES)} Cobalt and {len(self._settings.PIPED_INSTANCES)} Piped instances.")

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
            # === STRATEGY 1: COBALT ===
            res = await self._try_cobalt(video_id, track_info)
            if res.success: return await self._post_process(res)

            # === STRATEGY 2: PIPED ===
            res = await self._try_piped(video_id, track_info)
            if res.success: return await self._post_process(res)

            # === STRATEGY 3: DIRECT ===
            res = await self._try_direct(video_id, track_info)
            return await self._post_process(res)

    async def _try_cobalt(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        logger.info(f"🧬 [Cobalt] Attempting {video_id}...")
        
        instances = self._settings.COBALT_INSTANCES or []
        random.shuffle(instances)
        
        # Пробуем топ-5 случайных инстансов, чтобы не ждать вечно
        target_instances = instances[:5] 
        
        async with httpx.AsyncClient(timeout=self._settings.DOWNLOAD_TIMEOUT, verify=False, follow_redirects=True) as client:
            for base_url in target_instances:
                try:
                    payload = {
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "aFormat": "mp3",
                        "isAudioOnly": True,
                        "vQuality": "144" # Min video quality speeds up audio processing
                    }
                    headers = {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    
                    # logger.info(f"[Cobalt] Requesting {base_url}")
                    resp = await client.post(f"{base_url}/api/json", json=payload, headers=headers)
                    
                    if resp.status_code not in [200, 201]: 
                        logger.warning(f"[Cobalt] {base_url} returned {resp.status_code}: {resp.text[:100]}")
                        continue
                        
                    data = resp.json()
                    dl_url = data.get("url")
                    
                    # Иногда Cobalt возвращает 'picker' вместо url
                    if not dl_url and "picker" in data:
                        for item in data["picker"]:
                            if "audio" in item.get("type", ""):
                                dl_url = item.get("url")
                                break
                    
                    if not dl_url: 
                        logger.warning(f"[Cobalt] {base_url} no URL in response: {data}")
                        continue
                    
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_cobalt.mp3"
                    async with client.stream("GET", dl_url) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                                
                    if temp_path.stat().st_size > 5000:
                        logger.info(f"✅ [Cobalt] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                except Exception as e: 
                    logger.warning(f"[Cobalt] Error on {base_url}: {str(e)[:100]}")
                    continue
        
        return DownloadResult(success=False, error_message="All Cobalt instances failed")

    async def _try_piped(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        logger.info(f"🧪 [Piped] Attempting {video_id}...")
        
        instances = self._settings.PIPED_INSTANCES or []
        random.shuffle(instances)
        target_instances = instances[:6]
        
        async with httpx.AsyncClient(timeout=self._settings.DOWNLOAD_TIMEOUT, verify=False, follow_redirects=True) as client:
            for base_url in target_instances:
                try:
                    resp = await client.get(f"{base_url}/streams/{video_id}")
                    if resp.status_code != 200: 
                        logger.warning(f"[Piped] {base_url} returned {resp.status_code}")
                        continue
                        
                    streams = resp.json().get("audioStreams", [])
                    if not streams: continue
                    
                    dl_url = max(streams, key=lambda x: x.get("bitrate", 0)).get("url")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_piped.m4a"
                    
                    async with client.stream("GET", dl_url) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                                
                    if temp_path.stat().st_size > 5000:
                        logger.info(f"✅ [Piped] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                except Exception as e: 
                    logger.warning(f"[Piped] Error on {base_url}: {str(e)[:100]}")
                    continue
        return DownloadResult(success=False, error_message="Piped failed")

    async def _try_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        logger.warning(f"⚠️ [Direct] Attempting fallback for {video_id}...")
        url = f"https://www.youtube.com/watch?v={video_id}"
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'],
                    'player_skip': ['webpage', 'configs']
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        }
        if self.cookies_path.exists(): opts['cookiefile'] = str(self.cookies_path)
        try:
            loop = asyncio.get_running_loop()
            with yt_dlp.YoutubeDL(opts) as ydl: await loop.run_in_executor(None, lambda: ydl.download([url]))
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                if f.stat().st_size > 5000: return DownloadResult(success=True, file_path=f, track_info=track_info)
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