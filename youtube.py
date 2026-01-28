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
    🛡️ Titanium Downloader v18 (Direct Force).
    Strategy: Direct download ONLY using Android Client + PO Token.
    Removed dead proxies and failing APIs.
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Setup cookies
        self.cookies_path = self._settings.COOKIES_FILE
        if self._settings.COOKIES_CONTENT:
            try:
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(self._settings.COOKIES_CONTENT)
                logger.info("🍪 Cookies file created")
            except: pass

        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        po_status = "✅ YES" if self._settings.PO_TOKEN else "❌ NO"
        logger.info(f"🛡️ Titanium v18 (Direct Force). PO Token: {po_status}")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        cache_key = f"yt_search_v9:{query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
        opts = {
            'quiet': True, 
            'extract_flat': True, 
            'skip_download': True, 
            'ignoreerrors': True, 
            'nocheckcertificate': True,
            'socket_timeout': 10
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
            # === DIRECT DOWNLOAD ONLY ===
            logger.info(f"🚀 [Direct] Starting {video_id}...")
            res = await self._try_direct(video_id, track_info)
            return await self._post_process(res)

    def _build_extractor_args(self) -> dict:
        """Args for PO Token"""
        # 'android_creator' is the MVP for server-side downloads
        args = {
            'player_client': ['android_creator', 'android', 'ios'],
            'player_skip': ['webpage', 'configs', 'js']
        }
        
        if self._settings.PO_TOKEN:
            po = self._settings.PO_TOKEN
            if '+' not in po: po = f"web+{po}"
            args['po_token'] = [po]
            
        if self._settings.VISITOR_DATA:
            args['visitor_data'] = [self._settings.VISITOR_DATA]
            
        return args

    async def _try_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        loop = asyncio.get_running_loop()
        
        opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"),
            'quiet': True, 
            'no_warnings': True, 
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
            # Force IPv4 because IPv6 on Railway is sometimes broken for Google
            'source_address': '0.0.0.0', 
            'extractor_args': {'youtube': self._build_extractor_args()}
        }
        
        if self.cookies_path.exists(): opts['cookiefile'] = str(self.cookies_path)
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                await loop.run_in_executor(None, lambda: ydl.download([url]))
            
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                if f.exists() and f.stat().st_size > 10000:
                    logger.info(f"✅ [Direct] Success!")
                    return DownloadResult(success=True, file_path=f, track_info=track_info)
        except Exception as e:
            logger.error(f"[Direct] Failed: {e}")
        
        return DownloadResult(success=False, error_message="Direct failed", track_info=track_info)

    async def _post_process(self, result: DownloadResult) -> DownloadResult:
        if not result.success or not result.file_path: return result
        target = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        if result.file_path.suffix == ".mp3" and result.file_path.name == target.name: return result
        try:
            proc = await asyncio.create_subprocess_exec('ffmpeg', '-y', '-i', str(result.file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(target), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), timeout=120)
            if target.exists() and target.stat().st_size > 5000:
                try: result.file_path.unlink() 
                except: pass
                result.file_path = target
        except Exception: pass
        return result
