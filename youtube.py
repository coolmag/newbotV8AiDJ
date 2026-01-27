import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional, Dict, Any
import time

import httpx
import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)


class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v16 - Full Logging + Cobalt First
    """
    
    # Working instances (January 2025)
    COBALT_INSTANCES = [
        "https://api.cobalt.tools",
        "https://cobalt-api.ayo.tf",
        "https://co.eepy.today",
    ]
    
    PIPED_INSTANCES = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.adminforge.de", 
        "https://api.piped.yt",
        "https://pipedapi.r4fo.com",
    ]
    
    INVIDIOUS_INSTANCES = [
        "https://invidious.private.coffee",
        "https://yewtu.be",
        "https://inv.tux.pizza",
        "https://invidious.jing.rocks",
    ]
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Blacklist for failed instances (url -> timestamp)
        self._blacklist: Dict[str, float] = {}
        
        # Setup cookies
        self.cookies_path = self._settings.COOKIES_FILE
        if self._settings.COOKIES_CONTENT:
            try:
                self.cookies_path.write_text(self._settings.COOKIES_CONTENT, encoding="utf-8")
                logger.info("🍪 Cookies file created")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        # Load SOCKS5 proxies only
        self.proxies: List[str] = []
        if self._settings.PROXY_URL:
            self.proxies.append(self._settings.PROXY_URL)
        if self._settings.PROXIES_FILE.exists():
            try:
                for line in self._settings.PROXIES_FILE.read_text().splitlines():
                    p = line.strip()
                    if p and "socks5://" in p:
                        self.proxies.append(p)
            except:
                pass
        random.shuffle(self.proxies)
        self.proxies = self.proxies[:10]
        
        # Merge with config
        self.cobalt_list = list(set(
            (self._settings.COBALT_INSTANCES or []) + self.COBALT_INSTANCES
        ))
        self.piped_list = list(set(
            (self._settings.PIPED_INSTANCES or []) + self.PIPED_INSTANCES
        ))
        self.invidious_list = list(set(
            (self._settings.INVIDIOUS_INSTANCES or []) + self.INVIDIOUS_INSTANCES
        ))
        
        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        # Log status
        po = "✅" if self._settings.PO_TOKEN else "❌"
        logger.info(f"🛡️ Titanium v16 initialized")
        logger.info(f"   PO_TOKEN: {po}")
        logger.info(f"   Cobalt: {len(self.cobalt_list)}")
        logger.info(f"   Piped: {len(self.piped_list)}")
        logger.info(f"   Invidious: {len(self.invidious_list)}")
        logger.info(f"   Proxies: {len(self.proxies)}")

    def _is_blacklisted(self, url: str) -> bool:
        """Check if instance is temporarily blacklisted"""
        if url in self._blacklist:
            if time.time() - self._blacklist[url] < 300: # 5 min ban
                return True
            del self._blacklist[url]
        return False

    def _blacklist_instance(self, url: str):
        """Temporarily blacklist an instance"""
        self._blacklist[url] = time.time()
        logger.debug(f"Blacklisted: {url}")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Search YouTube"""
        cache_key = f"yt_search:{query}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        opts = {
            'quiet': True,
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
            'socket_timeout': 15,
        }
        
        if self.cookies_path.exists():
            opts['cookiefile'] = str(self.cookies_path)
        
        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
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
            
            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            return results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """Download with full fallback chain"""
        if not track_info:
            track_info = TrackInfo(
                identifier=video_id,
                title="Unknown",
                artist="Unknown", 
                duration=0,
                source=Source.YOUTUBE
            )

        # Check cache
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            logger.info(f"📁 [Cache] {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        logger.info(f"📥 [Download] Starting: {video_id}")

        async with self.semaphore:
            methods = [
                ("Cobalt", self._try_cobalt),
                ("Piped", self._try_piped),
                ("Invidious", self._try_invidious),
                ("Direct", self._try_direct),
            ]
            
            for name, method in methods:
                try:
                    result = await method(video_id, track_info)
                    if result.success:
                        return await self._convert_to_mp3(result)
                except Exception as e:
                    logger.warning(f"[{name}] Error: {e}")
            
            return DownloadResult(
                success=False,
                error_message="All download methods failed",
                track_info=track_info
            )

    async def _try_cobalt(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Cobalt API - best method currently"""
        instances = [u for u in self.cobalt_list if not self._is_blacklisted(u)]
        random.shuffle(instances)
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://cobalt.tools",
            "Referer": "https://cobalt.tools/",
        }
        
        for base_url in instances[:3]:
            try:
                logger.info(f"   → {base_url}")
                
                async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # New API format
                    payload = {
                        "url": url,
                        "downloadMode": "audio",
                        "audioFormat": "mp3"
                    }
                    
                    resp = await client.post(base_url, json=payload, headers=headers)
                    
                    # Fallback to old API
                    if resp.status_code == 404:
                        logger.info(f"   → Trying old API...")
                        resp = await client.post(
                            f"{base_url}/api/json",
                            json={"url": url, "isAudioOnly": True},
                            headers=headers
                        )
                    
                    logger.info(f"   → Status: {resp.status_code}")
                    
                    if resp.status_code not in (200, 201):
                        self._blacklist_instance(base_url)
                        continue
                    
                    data = resp.json()
                    logger.info(f"   → Response: {str(data)[:100]}")
                    
                    # Check for error
                    if data.get("status") == "error":
                        error = data.get("error", {})
                        logger.warning(f"   ⚠️ Error: {error.get('code', 'unknown')}")
                        continue
                    
                    # Extract download URL
                    dl_url = None
                    if data.get("status") == "tunnel" or data.get("status") == "redirect":
                        dl_url = data.get("url")
                    elif data.get("url"):
                        dl_url = data["url"]
                    elif data.get("audio"):
                        dl_url = data["audio"] if isinstance(data["audio"], str) else data["audio"].get("url")
                    elif data.get("picker"):
                        dl_url = data["picker"][0].get("url") if data["picker"] else None
                    
                    if not dl_url:
                        logger.warning(f"   ⚠️ No download URL")
                        continue
                    
                    logger.info(f"   → Downloading...")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_cobalt.mp3"
                    
                    async with client.stream("GET", dl_url, timeout=120.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    size = temp_path.stat().st_size if temp_path.exists() else 0
                    logger.info(f"   → Size: {size // 1024} KB")
                    
                    if size > 10000:
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                    else:
                        logger.warning(f"   ⚠️ File too small")
                        
            except httpx.TimeoutException:
                logger.warning(f"   ⚠️ Timeout")
                self._blacklist_instance(base_url)
            except Exception as e:
                logger.warning(f"   ⚠️ {type(e).__name__}: {str(e)[:50]}")
        
        return DownloadResult(success=False, track_info=track_info)

    async def _try_piped(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Piped API"""
        instances = [u for u in self.piped_list if not self._is_blacklisted(u)]
        random.shuffle(instances)
        
        for base_url in instances[:4]:
            try:
                logger.info(f"   → {base_url}")
                
                async with httpx.AsyncClient(timeout=20.0, verify=False, follow_redirects=True) as client:
                    resp = await client.get(f"{base_url}/streams/{video_id}")
                    
                    logger.info(f"   → Status: {resp.status_code}")
                    
                    if resp.status_code != 200:
                        self._blacklist_instance(base_url)
                        continue
                    
                    data = resp.json()
                    
                    if data.get("error"):
                        logger.warning(f"   ⚠️ API Error: {data.get('message', 'unknown')}")
                        continue
                    
                    streams = data.get("audioStreams", [])
                    if not streams:
                        logger.warning(f"   ⚠️ No audio streams")
                        continue
                    
                    best = max(streams, key=lambda x: x.get("bitrate", 0))
                    dl_url = best.get("url")
                    
                    if not dl_url:
                        continue
                    
                    logger.info(f"   → Downloading...")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_piped.m4a"
                    
                    async with client.stream("GET", dl_url, timeout=120.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    size = temp_path.stat().st_size if temp_path.exists() else 0
                    logger.info(f"   → Size: {size // 1024} KB")
                    
                    if size > 10000:
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                        
            except Exception as e:
                logger.warning(f"   ⚠️ {type(e).__name__}")
        
        return DownloadResult(success=False, track_info=track_info)

    async def _try_invidious(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Invidious API"""
        instances = [u for u in self.invidious_list if not self._is_blacklisted(u)]
        random.shuffle(instances)
        
        for base_url in instances[:4]:
            try:
                logger.info(f"   → {base_url}")
                
                async with httpx.AsyncClient(
                    timeout=20.0,
                    verify=False,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"}
                ) as client:
                    resp = await client.get(f"{base_url}/api/v1/videos/{video_id}")
                    
                    logger.info(f"   → Status: {resp.status_code}")
                    
                    if resp.status_code in (401, 403, 502, 503):
                        self._blacklist_instance(base_url)
                        continue
                    
                    if resp.status_code != 200:
                        continue
                    
                    data = resp.json()
                    formats = data.get("adaptiveFormats", [])
                    audio = [f for f in formats if f.get("type", "").startswith("audio/")]
                    
                    if not audio:
                        logger.warning(f"   ⚠️ No audio formats")
                        continue
                    
                    best = max(audio, key=lambda x: int(x.get("bitrate", 0)))
                    dl_url = best.get("url")
                    
                    if not dl_url:
                        continue
                    
                    logger.info(f"   → Downloading...")
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_inv.m4a"
                    
                    async with client.stream("GET", dl_url, timeout=120.0) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes(8192):
                                f.write(chunk)
                    
                    size = temp_path.stat().st_size if temp_path.exists() else 0
                    logger.info(f"   → Size: {size // 1024} KB")
                    
                    if size > 10000:
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
                        
            except Exception as e:
                logger.warning(f"   ⚠️ {type(e).__name__}")
        
        return DownloadResult(success=False, track_info=track_info)

    async def _try_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """Direct yt-dlp with PO_TOKEN"""
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Try with SOCKS5 proxies first, then direct
        candidates = [p for p in self.proxies if "socks5" in p][:3]
        candidates.append(None)  # Direct as last resort
        
        loop = asyncio.get_running_loop()
        
        for proxy in candidates:
            proxy_label = "Direct" if not proxy else proxy.split("@")[-1][:30] if "@" in proxy else proxy[:30]
            logger.info(f"   → {proxy_label}")
            
            # Build options
            opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': str(self._settings.DOWNLOADS_DIR / f"{video_id}_direct.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'socket_timeout': 30,
                'retries': 2,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android_creator', 'web'],
                        'player_skip': ['webpage', 'configs']
                    }
                }
            }
            
            # === INJECT PO_TOKEN ===
            if self._settings.PO_TOKEN:
                po = self._settings.PO_TOKEN
                # Format: "web+token" or just "token"
                if '+' not in po:
                    po = f"web+{po}"
                opts['extractor_args']['youtube']['po_token'] = [po]
                logger.info(f"   → PO_TOKEN injected")
            
            if self._settings.VISITOR_DATA:
                opts['extractor_args']['youtube']['visitor_data'] = [self._settings.VISITOR_DATA]
            
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
                        logger.info(f"   → Downloaded: {f.stat().st_size // 1024} KB")
                        return DownloadResult(success=True, file_path=f, track_info=track_info)
                
                logger.warning(f"   ⚠️ No output file")
                
            except yt_dlp.utils.DownloadError as e:
                err = str(e)
                if "Sign in" in err or "bot" in err.lower():
                    logger.warning(f"   ⚠️ Bot detection - need valid PO_TOKEN")
                elif "Requested format" in err:
                    logger.warning(f"   ⚠️ Format unavailable - try different client")
                else:
                    logger.warning(f"   ⚠️ {err[:60]}")
            except Exception as e:
                logger.warning(f"   ⚠️ {type(e).__name__}: {str(e)[:50]}")
            
            # Cleanup failed attempt
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}_direct.*"):
                try:
                    f.unlink()
                except:
                    pass
        
        return DownloadResult(success=False, track_info=track_info)

    async def _convert_to_mp3(self, result: DownloadResult) -> DownloadResult:
        """Convert to MP3 using FFmpeg"""
        if not result.success or not result.file_path:
            return result
        
        src = result.file_path
        target = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        
        # Already MP3 with correct name
        if src == target:
            return result
        
        # Target already exists
        if target.exists() and target.stat().st_size > 5000:
            try:
                src.unlink()
            except:
                pass
            result.file_path = target
            return result
        
        # Convert
        try:
            logger.info(f"🎵 Converting to MP3...")
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', str(src),
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2',
                str(target),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.wait_for(proc.wait(), timeout=120)
            
            if target.exists() and target.stat().st_size > 5000:
                try:
                    src.unlink()
                except:
                    pass
                result.file_path = target
                logger.info(f"✅ Converted: {target.name}")
            else:
                logger.warning("FFmpeg produced empty file")
                
        except asyncio.TimeoutError:
            logger.error("FFmpeg timeout")
        except FileNotFoundError:
            logger.warning("FFmpeg not found")
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
        
        return result