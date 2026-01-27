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
    🛡️ Titanium Downloader v12 - PO Token FIXED
    
    Key fixes:
    - Correct PO Token format for yt-dlp extractor_args
    - Browser headers for Cobalt API
    - Invidious local=true for geo-bypass
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Setup cookies file
        self.cookies_path = self._settings.COOKIES_FILE
        if self._settings.COOKIES_CONTENT:
            try:
                # Используем write_text для безопасности
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
        visitor_status = "✅ YES" if self._settings.VISITOR_DATA else "❌ NO"
        proxy_count = len(self.proxies)
        
        logger.info(f"🛡️ Titanium v12 initialized")
        logger.info(f"   PO_TOKEN: {po_status}")
        logger.info(f"   VISITOR_DATA: {visitor_status}")
        logger.info(f"   Proxies loaded: {proxy_count}")

    def _load_proxies(self):
        """Load proxies from config and file"""
        if self._settings.PROXY_URL:
            self.proxies.append(self._settings.PROXY_URL)
            
        if self._settings.PROXIES_FILE.exists():
            try:
                with open(self._settings.PROXIES_FILE, "r") as f:
                    for line in f:
                        p = line.strip()
                        # Only SOCKS5 and HTTP/HTTPS proxies, no SOCKS4
                        if p and ("socks5://" in p or "http" in p):
                            if p not in self.proxies:
                                self.proxies.append(p)
            except Exception as e:
                logger.error(f"Failed to load proxies: {e}")
                
        random.shuffle(self.proxies)

    def _build_extractor_args(self) -> dict:
        """Build YouTube extractor args with PO Token if available"""
        # Используем android_creator - это самый надежный клиент сейчас
        args = {
            'player_client': ['android_creator', 'web_creator', 'mweb'],
            'player_skip': ['webpage', 'configs']
        }
        
        # === CRITICAL: Correct PO Token format ===
        if self._settings.PO_TOKEN:
            # Format: "client+token" (e.g., "web+abc123...")
            po_token = self._settings.PO_TOKEN
            
            # If token doesn't have client prefix, assume web+
            if '+' not in po_token:
                po_token = f"web+{po_token}"
            
            args['po_token'] = [po_token]
            logger.debug(f"PO Token configured")
        
        if self._settings.VISITOR_DATA:
            args['visitor_data'] = [self._settings.VISITOR_DATA]
            
        return args

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Search YouTube for tracks"""
        cache_key = f"yt_search_v4:{query}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
        opts = {
            'quiet': True, 
            'extract_flat': True, 
            'skip_download': True, 
            'ignoreerrors': True, 
            'nocheckcertificate': True,
            'socket_timeout': 15,
            # Важно: для поиска тоже можно использовать extractor_args, но аккуратно
            # 'extractor_args': {'youtube': self._build_extractor_args()} 
        }
        
        if self.cookies_path.exists():
            opts['cookiefile'] = str(self.cookies_path)
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(
                    None, 
                    lambda: ydl.extract_info(search_query, download=False)
                )
            
            results = []
            if info:
                entries = info.get('entries', []) if 'entries' in info else [info]
                for entry in entries:
                    if not entry:
                        continue
                    duration = int(entry.get('duration') or 0)
                    if duration > 1200:  # Skip videos > 20 min
                        continue
                        
                    results.append(TrackInfo(
                        identifier=entry.get('id'),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('uploader') or entry.get('channel', 'Unknown'),
                        duration=duration,
                        source=Source.YOUTUBE
                    ))
            
            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            return results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """Download audio with multi-method fallback"""
        if not track_info:
            track_info = TrackInfo(
                identifier=video_id, 
                title="Unknown", 
                artist="Unknown", 
                duration=0,
                source=Source.YOUTUBE
            )

        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            logger.info(f"📁 Cache hit: {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            methods = [
                ("Invidious", self._try_invidious), # Priority 1
                ("Piped", self._try_piped),         # Priority 2
                ("Cobalt", self._try_cobalt),       # Priority 3
                ("Direct", self._try_direct),       # Priority 4
            ]
            
            for name, method in methods:
                try:
                    result = await method(video_id, track_info)
                    if result.success:
                        return await self._post_process(result)
                except Exception as e:
                    # logger.warning(f"[{name}] Error: {e}")
                    continue
            
            return DownloadResult(
                success=False, 
                error_message="All download methods failed",
                track_info=track_info
            )

    async def _try_invidious(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Try Invidious instances with local=true for geo-bypass"""
        instances = list(self._settings.INVIDIOUS_INSTANCES or [])
        random.shuffle(instances)
        
        for base_url in instances[:6]:
            try:
                async with httpx.AsyncClient(timeout=25.0, verify=False, follow_redirects=True) as client: # Changed timeout to 25.0
                    # Use local=true to force server-side proxy
                    api_url = f"{base_url}/api/v1/videos/{video_id}?local=true"
                    resp = await client.get(api_url)
                    
                    if resp.status_code != 200:
                        continue
                    
                    data = resp.json()
                    formats = data.get("adaptiveFormats", [])
                    
                    # Filter audio-only formats
                    audio_formats = [
                        f for f in formats 
                        if f.get("type", "").startswith("audio/")
                    ]
                    
                    if not audio_formats:
                        continue
                    
                    # Select best bitrate
                    best = max(audio_formats, key=lambda x: int(x.get("bitrate", 0)))
                    dl_url = best.get("url")
                    
                    if not dl_url:
                        continue
                    
                    # Download
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_inv.m4a"
                    async with client.stream("GET", dl_url, timeout=60.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    if temp_path.exists() and temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Invidious] {video_id} via {base_url}")
                        return DownloadResult(
                            success=True, 
                            file_path=temp_path, 
                            track_info=track_info
                        )
                        
            except Exception as e:
                # logger.debug(f"[Invidious] {base_url} failed: {e}")
                continue
                
        return DownloadResult(success=False, track_info=track_info)

    async def _try_piped(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Try Piped API instances"""
        instances = list(self._settings.PIPED_INSTANCES or [])
        random.shuffle(instances)
        
        for base_url in instances[:4]:
            try:
                async with httpx.AsyncClient(timeout=20.0, verify=False, follow_redirects=True) as client:
                    resp = await client.get(f"{base_url}/streams/{video_id}")
                    
                    if resp.status_code != 200:
                        continue
                    
                    data = resp.json()
                    streams = data.get("audioStreams", [])
                    
                    if not streams:
                        continue
                    
                    # Best bitrate
                    best = max(streams, key=lambda x: x.get("bitrate", 0))
                    dl_url = best.get("url")
                    
                    if not dl_url:
                        continue
                    
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_piped.m4a"
                    async with client.stream("GET", dl_url, timeout=60.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    if temp_path.exists() and temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Piped] {video_id} via {base_url}")
                        return DownloadResult(
                            success=True, 
                            file_path=temp_path, 
                            track_info=track_info
                        )
                        
            except Exception as e:
                # logger.debug(f"[Piped] {base_url} failed: {e}")
                continue
                
        return DownloadResult(success=False, track_info=track_info)

    async def _try_cobalt(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Try Cobalt API with browser headers"""
        instances = list(self._settings.COBALT_INSTANCES or [])
        random.shuffle(instances)
        
        # Browser-like headers to bypass jwt.missing
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://cobalt.tools/",
            "Origin": "https://cobalt.tools",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site"
        }
        
        for base_url in instances[:4]: # Try up to 4 Cobalt instances
            try:
                async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Try new API format first
                    payload = {
                        "url": url,
                        "downloadMode": "audio",
                        "audioFormat": "mp3"
                    }
                    
                    resp = await client.post(base_url, json=payload, headers=headers)
                    
                    # Fallback to old API format
                    if resp.status_code == 404:
                        old_payload = {"url": url, "isAudioOnly": True}
                        resp = await client.post(
                            f"{base_url}/api/json", 
                            json=old_payload, 
                            headers=headers
                        )
                    
                    if resp.status_code not in (200, 201):
                        continue
                    
                    data = resp.json()
                    
                    # Handle different response formats
                    dl_url = None
                    if data.get("status") == "tunnel" or data.get("status") == "redirect":
                        dl_url = data.get("url")
                    elif data.get("url"):
                        dl_url = data.get("url")
                    elif data.get("audio"):
                        dl_url = data["audio"].get("url") if isinstance(data["audio"], dict) else data["audio"]
                    elif data.get("picker"):
                        dl_url = data["picker"][0].get("url") if data["picker"] else None
                    
                    if not dl_url:
                        continue
                    
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_cobalt.mp3"
                    async with client.stream("GET", dl_url, timeout=60.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    if temp_path.exists() and temp_path.stat().st_size > 10000:
                        logger.info(f"✅ [Cobalt] {video_id} via {base_url}")
                        return DownloadResult(
                            success=True, 
                            file_path=temp_path, 
                            track_info=track_info
                        )
                        
            except Exception as e:
                continue
                
        return DownloadResult(success=False, track_info=track_info)

    async def _try_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Direct yt-dlp download with PO Token and proxy rotation"""
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Try with proxies first, then direct
        candidates = self.proxies[:5] + [None]
        
        loop = asyncio.get_running_loop()
        
        for proxy in candidates:
            proxy_label = proxy.split(" @")[-1][:30] if proxy else "Direct"
            logger.info(f"🔧 [Direct] Trying {video_id} via {proxy_label}")
            
            opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'socket_timeout': 30,
                'retries': 2,
                
                # === CORRECT EXTRACTOR ARGS WITH PO TOKEN ===
                'extractor_args': {
                    'youtube': self._build_extractor_args()
                }
            }
            
            if proxy:
                opts['proxy'] = proxy
                
            if self.cookies_path.exists():
                opts['cookiefile'] = str(self.cookies_path)
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    await loop.run_in_executor(None, lambda: ydl.download([url]))
                
                # Find downloaded file
                for ext in ['m4a', 'webm', 'mp3', 'opus', 'ogg']:
                    f = self._settings.DOWNLOADS_DIR / f"{video_id}_direct.{ext}"
                    if f.exists() and f.stat().st_size > 10000:
                        logger.info(f"✅ [Direct] {video_id} via {proxy_label}")
                        return DownloadResult(
                            success=True, 
                            file_path=f, 
                            track_info=track_info
                        )
                        
            except yt_dlp.utils.DownloadError as e:
                # logger.debug(f"[Direct] Download error: {e}")
                pass
            except Exception as e:
                # logger.debug(f"[Direct] Error: {e}")
                pass
            
            # Cleanup failed attempt
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                try: f.unlink()
                except: pass
        
        return DownloadResult(
            success=False, 
            error_message="Direct download failed",
            track_info=track_info
        )

    async def _post_process(self, result: DownloadResult) -> DownloadResult:
        """Convert to MP3 if needed"""
        if not result.success or not result.file_path:
            return result
        
        src = result.file_path
        target = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        
        # Already correct format
        if src.suffix == ".mp3" and src == target:
            return result
        
        # Already exists
        if target.exists() and target.stat().st_size > 5000:
            try: src.unlink()
            except: pass
            result.file_path = target
            return result
        
        # Convert with FFmpeg
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', str(src),
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2',
                str(target),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.wait_for(proc.wait(), timeout=120)
            
            if target.exists() and target.stat().st_size > 5000:
                try: src.unlink()
                except: pass
                result.file_path = target
            else:
                logger.warning("FFmpeg produced empty file")
                
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
        
        return result