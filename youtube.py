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
    🛡️ Titanium Downloader v19 (Polymorphic).
    Fixes the 'Client Mismatch' bug.
    Strategy:
    1. Web Client + PO Token (Matching signatures)
    2. iOS Client (Native bypass)
    3. TV Client (Embedded bypass)
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.cookies_path = self._settings.COOKIES_FILE
        if self._settings.COOKIES_CONTENT:
            try:
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(self._settings.COOKIES_CONTENT)
                logger.info("🍪 Cookies file created")
            except: pass

        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        po_status = "✅ YES" if self._settings.PO_TOKEN else "❌ NO"
        logger.info(f"🛡️ Titanium v19 (Polymorphic). PO Token: {po_status}")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        cache_key = f"yt_search_v10:{query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
        # Use simple android client for search (fastest)
        opts = {
            'quiet': True, 'extract_flat': True, 'skip_download': True,
            'ignoreerrors': True, 'nocheckcertificate': True, 'socket_timeout': 10,
            'extractor_args': {'youtube': {'player_client': ['android']}}
        }
        
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
            # === STRATEGY 1: AUTHENTICATED WEB (Requires PO Token) ===
            if self._settings.PO_TOKEN:
                logger.info(f"🚀 [1/3] Trying Web Client + PO Token...")
                res = await self._try_download(video_id, mode="web_token")
                if res.success: return await self._post_process(res, track_info)

            # === STRATEGY 2: IOS BYPASS ===
            logger.info(f"🍏 [2/3] Trying iOS Client...")
            res = await self._try_download(video_id, mode="ios")
            if res.success: return await self._post_process(res, track_info)

            # === STRATEGY 3: TV EMBEDDED ===
            logger.info(f"📺 [3/3] Trying TV Client...")
            res = await self._try_download(video_id, mode="tv")
            return await self._post_process(res, track_info)

    async def _try_download(self, video_id: str, mode: str) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        loop = asyncio.get_running_loop()
        
        # Base Options
        opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_{mode}.%(ext)s"),
            'quiet': True, 'no_warnings': True, 'nocheckcertificate': True,
            'socket_timeout': 30, 'retries': 3,
        }

        # Config per mode
        if mode == "web_token":
            # Strict pairing: Web Client + Web Token
            po = self._settings.PO_TOKEN
            if '+' not in po: po = f"web+{po}"
            
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['web', 'web_creator'],
                    'po_token': [po],
                    'player_skip': ['webpage', 'configs']
                }
            }
            if self._settings.VISITOR_DATA:
                opts['extractor_args']['youtube']['visitor_data'] = [self._settings.VISITOR_DATA]
            
            # Cookies are ESSENTIAL for Web Client
            if self.cookies_path.exists(): 
                opts['cookiefile'] = str(self.cookies_path)

        elif mode == "ios":
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['ios'],
                    'player_skip': ['webpage', 'configs', 'js']
                }
            }
            # Remove cookies to avoid "Sign in" conflicts on iOS
            
        elif mode == "tv":
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['tv_embedded'],
                    'player_skip': ['webpage', 'configs']
                }
            }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                await loop.run_in_executor(None, lambda: ydl.download([url]))
            
            # Check file
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_{mode}.*"):
                if f.exists() and f.stat().st_size > 10000:
                    logger.info(f"✅ Success via {mode}")
                    return DownloadResult(success=True, file_path=f)
                    
        except Exception as e:
            # logger.warning(f"Fail {mode}: {e}")
            pass
        
        return DownloadResult(success=False)

    async def _post_process(self, result: DownloadResult, track_info: TrackInfo) -> DownloadResult:
        result.track_info = track_info
        if not result.success or not result.file_path: return result
        
        target = self._settings.DOWNLOADS_DIR / f"{track_info.identifier}.mp3"
        
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', str(result.file_path),
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2',
                str(target),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.wait_for(proc.wait(), timeout=120)
            
            if target.exists() and target.stat().st_size > 5000:
                try: result.file_path.unlink() 
                except: pass
                result.file_path = target
        except Exception: pass
        
        return result