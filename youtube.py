import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import yt_dlp
from ytmusicapi import YTMusic
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService
from proxy_service import ProxyManager

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🎵 YouTube Music Edition (v44 - V2Ray + Field Fix).
    Search: ytmusicapi (Direct).
    Download: yt-dlp + V2Ray Proxy Rotation.
    Fixes: 'author' -> 'uploader' mismatch.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(1)
        self.ytmusic = YTMusic() 
        
        # Инициализируем твой ProxyManager
        proxies_file = Path("hiddify_compatible_v2ray_proxies.txt")
        self._proxy_manager = ProxyManager(proxies_file)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Поиск через YouTube Music API"""
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
            
        if not query or not query.strip(): return []
            
        logger.info(f"🔎 YTMusic Search: {query}")
        
        loop = asyncio.get_running_loop()
        try:
            search_results = await loop.run_in_executor(None, lambda: self.ytmusic.search(query, filter="songs", limit=limit))
            
            results = []
            for item in search_results:
                video_id = item.get('videoId')
                if not video_id: continue
                
                artists = ", ".join([a['name'] for a in item.get('artists', [])])
                duration_text = item.get('duration', '0:00')
                try:
                    parts = duration_text.split(':')
                    duration = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(parts[0])
                except:
                    duration = 0
                
                if duration > 900: continue

                # 👇 ИСПРАВЛЕНО: uploader вместо author/artist
                track = TrackInfo(
                    identifier=video_id,
                    title=item.get('title'),
                    uploader=artists, # <--- ВОТ ТУТ БЫЛА ОШИБКА
                    duration=duration,
                    thumbnail_url=item.get('thumbnails', [{}])[-1].get('url'),
                    source="ytmusic"
                )
                results.append(track)
            
            logger.info(f"✅ Found {len(results)} tracks on YTMusic")
            return results

        except Exception as e:
            logger.error(f"❌ YTMusic Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            logger.info(f"✅ Cache hit for {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        # 🚀 ЗАПУСКАЕМ ПРОКСИ ПЕРЕД СКАЧИВАНИЕМ
        proxy_started = False
        try:
            proxy_started = await self._proxy_manager.start_proxy()
            
            if not proxy_started:
                logger.error("Failed to start V2Ray proxy. Trying direct download...")
            
            async with self.semaphore:
                await asyncio.sleep(random.randint(2, 5))
                logger.info(f"🎧 Downloading {video_id} via Proxy: {self._proxy_manager.active_proxy_url if proxy_started else 'Direct'}...")
                
                return await self._download_smart(video_id, final_path, track_info)
                
        finally:
            if proxy_started:
                self._proxy_manager.stop_proxy()

    async def _download_smart(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        temp_path = str(target_path).replace(".mp3", "_temp")
        
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        }
        
        if self._proxy_manager.active_proxy_url:
            opts['proxy'] = self._proxy_manager.active_proxy_url
            logger.info(f"🔗 Using Proxy for yt-dlp: {self._proxy_manager.active_proxy_url}")

        clients = [
            ['android', 'android_music'], 
            ['ios'],                      
            ['tv_embedded', 'web_creator']
        ]

        for client_list in clients:
            try:
                opts['extractor_args'] = {
                    'youtube': {
                        'player_client': client_list,
                        'player_skip': ['webpage', 'configs', 'js'],
                    }
                }
                
                logger.info(f"Trying clients: {client_list}")
                
                loop = asyncio.get_running_loop()
                url = f"https://music.youtube.com/watch?v={video_id}"
                await loop.run_in_executor(None, lambda: self._run_yt_dlp(opts, url))
                
                paths_to_check = [Path(temp_path + ".mp3"), Path(temp_path)]
                for p in paths_to_check:
                    if p.exists() and p.stat().st_size > 10000:
                        if p != target_path:
                            if target_path.exists(): target_path.unlink()
                            p.rename(target_path)
                        logger.info(f"✅ Success with {client_list}")
                        return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            
            except Exception as e:
                logger.warning(f"Client {client_list} failed: {e}")
                continue

        return DownloadResult(success=False, error_message="All download methods failed")

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])