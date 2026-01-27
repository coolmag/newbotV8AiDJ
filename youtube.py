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
    Titanium Downloader v9 (Direct Force).
    Strategy: Direct download using Rotated Proxies + Optimized Headers.
    Removed dead Cobalt/Piped logic to save time.
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

        self.proxies = []
        self._load_proxies()

        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        self.search_opts = {
            'quiet': True, 
            'extract_flat': True, 
            'skip_download': True, 
            'ignoreerrors': True, 
            'nocheckcertificate': True,
            'socket_timeout': 10
        }

        logger.info(f"🛡 Titanium Direct Engine. Proxies loaded: {len(self.proxies)}")

    def _load_proxies(self):
        if self._settings.PROXY_URL:
            self.proxies.append(self._settings.PROXY_URL)
        if self._settings.PROXIES_FILE.exists():
            try:
                with open(self._settings.PROXIES_FILE, "r") as f:
                    for line in f:
                        p = line.strip()
                        if p and "://" in p: self.proxies.append(p)
            except Exception as e: logger.error(f"Failed to load proxies: {e}")
        random.shuffle(self.proxies)

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
            # ONLY DIRECT ROTATION
            res = await self._try_direct_rotated(video_id, track_info)
            return await self._post_process(res)

    async def _try_direct_rotated(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Try proxies, then direct as last resort
        candidates = self.proxies[:8] if self.proxies else []
        candidates.append(None) 
        
        loop = asyncio.get_running_loop()
        
        for proxy in candidates:
            proxy_log = proxy if proxy else "Direct"
            logger.info(f"⚠️ [Direct] Attempting {video_id} via {proxy_log}...")
            
            opts = {
                # Try specific m4a first (itag 140), then any best audio
                'format': '140/bestaudio/best', 
                'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                # Mobile User Agent often bypasses 'Sign in' checks
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android'],
                        'player_skip': ['webpage', 'configs', 'js']
                    }
                }
            }
            
            if proxy: 
                opts['proxy'] = proxy
            
            if self.cookies_path.exists(): 
                opts['cookiefile'] = str(self.cookies_path)
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    await loop.run_in_executor(None, lambda: ydl.download([url]))
                
                # Check for ANY file downloaded
                for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                    if f.stat().st_size > 5000:
                        logger.info(f"✅ [Direct] Success via {proxy_log}")
                        return DownloadResult(success=True, file_path=f, track_info=track_info)
            except Exception as e:
                logger.warning(f"[Direct] Failed via {proxy_log}: {str(e)[:100]}")
                continue
                
        return DownloadResult(success=False, error_message="All proxies failed")

    async def _post_process(self, result: DownloadResult) -> DownloadResult:
        if not result.success or not result.file_path: return result
        target = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        if result.file_path.suffix == ".mp3" and result.file_path.name == target.name: return result
        try:
            proc = await asyncio.create_subprocess_exec('ffmpeg', '-y', '-i', str(result.file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '4', str(target), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
            if target.exists() and target.stat().st_size > 0:
                try: result.file_path.unlink() 
                except: pass
                result.file_path = target
        except Exception as e: logger.error(f"FFmpeg error: {e}")
        return result