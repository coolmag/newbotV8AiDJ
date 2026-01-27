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
    🛡️ Titanium Downloader v14 (Final).
    Features:
    - Invidious Proxying (local=true) -> Bypasses IP bans 100%.
    - Smart PO Token Injection -> Fixes Direct Download.
    - Browser Headers -> Fixes Cobalt API.
    - Full Debug Logging.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Setup cookies
        self.cookies_path = self._settings.COOKIES_FILE
        if self._settings.COOKIES_CONTENT:
            try:
                # Use open/write for compatibility
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(self._settings.COOKIES_CONTENT)
                logger.info("🍪 Cookies file created")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        # Load proxies
        self.proxies: List[str] = []
        self._load_proxies()

        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        # Log status
        po_status = "✅ YES" if self._settings.PO_TOKEN else "❌ NO"
        
        logger.info(f"🛡️ Titanium v14 initialized")
        logger.info(f"   PO_TOKEN: {po_status}")
        logger.info(f"   Proxies loaded: {len(self.proxies)}")
        logger.info(f"   Cobalt: {len(self._settings.COBALT_INSTANCES or [])}")
        logger.info(f"   Invidious: {len(self._settings.INVIDIOUS_INSTANCES or [])}")

    def _load_proxies(self):
        """Load proxies"""
        if self._settings.PROXY_URL:
            self.proxies.append(self._settings.PROXY_URL)
            
        if self._settings.PROXIES_FILE.exists():
            try:
                with open(self._settings.PROXIES_FILE, "r") as f:
                    for line in f:
                        p = line.strip()
                        # Prefer HTTP/HTTPS/SOCKS5
                        if p and "://" in p:
                            if p not in self.proxies:
                                self.proxies.append(p)
            except Exception as e:
                logger.error(f"Failed to load proxies: {e}")
                
        random.shuffle(self.proxies)

    def _build_extractor_args(self) -> dict:
        """Build YouTube extractor args with PO Token"""
        args = {
            'player_client': ['android_creator', 'web_creator', 'ios'],
            'player_skip': ['webpage', 'configs']
        }
        
        if self._settings.PO_TOKEN:
            po_token = self._settings.PO_TOKEN
            if '+' not in po_token:
                po_token = f"web+{po_token}"
            args['po_token'] = [po_token]
        
        if self._settings.VISITOR_DATA:
            args['visitor_data'] = [self._settings.VISITOR_DATA]
            
        return args

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        cache_key = f"yt_search_v5:{query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
        opts = {
            'quiet': True, 
            'extract_flat': True, 
            'skip_download': True, 
            'ignoreerrors': True, 
            'nocheckcertificate': True,
            'socket_timeout': 15,
        }
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
            
            results = []
            if info:
                entries = info.get('entries', []) if 'entries' in info else [info]
                for entry in entries:
                    if not entry: continue
                    if int(entry.get('duration') or 0) > 1200: continue
                        
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
            logger.info(f"📁 [Cache] Found: {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            # 1. Invidious (Best chance for Audio)
            res = await self._try_invidious(video_id, track_info)
            if res.success: return await self._post_process(res)

            # 2. Piped
            res = await self._try_piped(video_id, track_info)
            if res.success: return await self._post_process(res)

            # 3. Cobalt
            res = await self._try_cobalt(video_id, track_info)
            if res.success: return await self._post_process(res)

            # 4. Direct
            res = await self._try_direct(video_id, track_info)
            return await self._post_process(res)

    async def _try_invidious(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        instances = list(self._settings.INVIDIOUS_INSTANCES or [])
        random.shuffle(instances)
        
        for base_url in instances[:6]:
            try:
                async with httpx.AsyncClient(timeout=25.0, verify=False, follow_redirects=True) as client:
                    # LOCAL=TRUE IS CRITICAL FOR RAILWAY
                    api_url = f"{base_url}/api/v1/videos/{video_id}?local=true"
                    resp = await client.get(api_url)
                    
                    if resp.status_code != 200:
                        logger.warning(f"[Invidious] {base_url} status {resp.status_code}: {resp.text[:100]}")
                        continue
                    
                    data = resp.json()
                    
                    # Try adaptiveFormats (Audio Only)
                    formats = data.get("adaptiveFormats", [])
                    audio_formats = [f for f in formats if f.get("type", "").startswith("audio/")]
                    
                    if not audio_formats: 
                        logger.warning(f"[Invidious] {base_url} no audio formats found.")
                        continue
                    
                    # Best bitrate
                    best = max(audio_formats, key=lambda f: int(f.get("bitrate", 0))) # Fixed x to f
                    dl_url = best.get("url")
                    
                    if not dl_url: 
                        logger.warning(f"[Invidious] {base_url} no download URL found.")
                        continue
                        
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_inv.m4a"
                    async with client.stream("GET", dl_url, timeout=90.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    if temp_path.exists() and temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Invidious] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                        
            except Exception as e:
                logger.warning(f"[Invidious] Error on {base_url}: {str(e)[:100]}")
                continue
        return DownloadResult(success=False)

    async def _try_piped(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        instances = list(self._settings.PIPED_INSTANCES or [])
        random.shuffle(instances)
        
        for base_url in instances[:4]:
            try:
                async with httpx.AsyncClient(timeout=20.0, verify=False, follow_redirects=True) as client:
                    resp = await client.get(f"{base_url}/streams/{video_id}")
                    if resp.status_code != 200: 
                        logger.warning(f"[Piped] {base_url} status {resp.status_code}: {resp.text[:100]}")
                        continue
                    
                    data = resp.json()
                    streams = data.get("audioStreams", [])
                    if not streams: 
                        logger.warning(f"[Piped] {base_url} no audio streams found.")
                        continue
                    
                    dl_url = max(streams, key=lambda x: x.get("bitrate", 0)).get("url")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_piped.m4a"
                    
                    async with client.stream("GET", dl_url, timeout=60.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    if temp_path.exists() and temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Piped] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
            except Exception as e: 
                logger.warning(f"[Piped] Error on {base_url}: {str(e)[:100]}")
                continue
        return DownloadResult(success=False)

    async def _try_cobalt(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        instances = list(self._settings.COBALT_INSTANCES or [])
        random.shuffle(instances)
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Origin": "https://cobalt.tools",
            "Referer": "https://cobalt.tools/",
        }
        
        for base_url in instances[:3]:
            try:
                async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                    payload = {"url": f"https://www.youtube.com/watch?v={video_id}", "downloadMode": "audio"}
                    
                    # Try v10 then v7
                    resp = await client.post(base_url, json=payload, headers=headers)
                    if resp.status_code == 404:
                        resp = await client.post(f"{base_url}/api/json", json={"url": payload["url"], "isAudioOnly": True}, headers=headers)
                    
                    if resp.status_code not in (200, 201): 
                        logger.warning(f"[Cobalt] {base_url} status {resp.status_code}: {resp.text[:100]}")
                        continue
                    
                    data = resp.json()
                    dl_url = data.get("url") or data.get("picker", [{}])[0].get("url")
                    if not dl_url: 
                        logger.warning(f"[Cobalt] {base_url} missing URL. Data: {str(data)[:100]}")
                        continue
                    
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_cobalt.mp3"
                    async with client.stream("GET", dl_url, timeout=60.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    if temp_path.exists() and temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Cobalt] Success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
            except Exception as e: 
                logger.warning(f"[Cobalt] Error on {base_url}: {str(e)[:100]}")
                continue
        return DownloadResult(success=False, error_message="All Cobalt instances failed")

    async def _try_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Proxies (SOCKS5 preferred)
        candidates = [p for p in self.proxies if "socks5" in p][:3] + [None]
        
        loop = asyncio.get_running_loop()
        
        for proxy in candidates:
            proxy_label = "Direct" if not proxy else proxy.split("@")[-1][:20]
            logger.info(f"🔧 [Direct] Try via {proxy_label}")
            
            opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'socket_timeout': 30,
                'retries': 2,
                
                'extractor_args': {'youtube': self._build_extractor_args()}
            }
            
            if proxy: opts['proxy'] = proxy
            if self.cookies_path.exists(): opts['cookiefile'] = str(self.cookies_path)
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    await loop.run_in_executor(None, lambda: ydl.download([url]))
                
                for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                    if f.exists() and f.stat().st_size > 10000:
                        logger.info(f"✅ [Direct] Success via {proxy_label}")
                        return DownloadResult(success=True, file_path=f, track_info=track_info)
            except Exception as e:
                logger.warning(f"[Direct] Failed via {proxy_label}: {str(e)[:100]}")
                pass # Continue to next proxy
        
        return DownloadResult(success=False, error_message="All direct methods failed", track_info=track_info)

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
            else:
                logger.warning("FFmpeg produced empty file")
        except Exception as e: logger.error(f"FFmpeg error: {e}")
        return result