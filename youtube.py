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
from proxy_service import ProxyManager # Import ProxyManager

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🎵 YouTube Music Edition (v43 - 2026 Fix).
    Fixes: js_runtimes format + updated player clients for 2026
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(1)
        self.ytmusic = YTMusic() 
        self._proxy_manager = ProxyManager(settings.V2RAY_PROXIES_FILE) # Initialize ProxyManager

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
        if not query or not query.strip(): 
            return []
        logger.info(f"🔎 YTMusic Search: {query}")
        loop = asyncio.get_running_loop()
        try:
            search_results = await loop.run_in_executor(
                None, 
                lambda: self.ytmusic.search(query, filter="songs", limit=limit)
            )
            results = []
            for item in search_results:
                video_id = item.get('videoId')
                if not video_id: 
                    continue
                artists = ", ".join([a['name'] for a in item.get('artists', [])])
                duration_text = item.get('duration', '0:00')
                try:
                    parts = duration_text.split(':')
                    duration = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(parts[0])
                except (ValueError, TypeError):
                    duration = 0
                if duration > 900: 
                    continue
                track = TrackInfo(
                    identifier=video_id,
                    title=item.get('title'),
                    artist=artists,
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

    def _get_base_opts(self, temp_path: str) -> dict:
        """Базовые опции для yt-dlp (2026 формат)"""
        opts = { # Create opts dictionary
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': temp_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            # ✅ ПРАВИЛЬНЫЙ ФОРМАТ 2026: словарь с конфигом
            'js_runtimes': {
                'node': {},  # Пустой конфиг = дефолтные настройки
            },
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192'
            }],
        }
        if self._proxy_manager.active_proxy_url: # Add proxy if available
            opts['proxy'] = self._proxy_manager.active_proxy_url
            logger.debug(f"Using proxy for yt-dlp: {self._proxy_manager.active_proxy_url}")
        return opts

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            logger.info(f"✅ Cache hit for {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)
        
        proxy_started = False
        try:
            proxy_started = await self._proxy_manager.start_proxy()
            if not proxy_started:
                logger.error("Failed to start proxy, aborting download.")
                return DownloadResult(success=False, error_message="Failed to start V2Ray proxy")

            async with self.semaphore:
                await asyncio.sleep(random.uniform(2, 5))
                logger.info(f"🎧 Downloading {video_id}...")
                
                # Пробуем разные методы по очереди
                methods = [
                    ("WEB_MUSIC", self._download_web_music),
                    ("ANDROID_MUSIC", self._download_android_music),
                    ("MWEB", self._download_mweb),
                    ("TVHTML5", self._download_tv),
                    ("DEFAULT", self._download_default),
                ]
                
                for method_name, method_func in methods:
                    try:
                        logger.info(f"--> Trying method: {method_name}")
                        result = await method_func(video_id, final_path, track_info)
                        if result.success:
                            logger.info(f"✅ Success with method: {method_name}")
                            return result
                        else:
                            logger.warning(f"Method {method_name} failed softly, trying next.")
                    except Exception as e:
                        logger.warning(f"❌ Method {method_name} failed with exception: {e}")
                        continue
                
                logger.error(f"❌ All methods failed for {video_id}")
                return DownloadResult(success=False, error_message="All download methods failed")
        finally:
            if proxy_started:
                self._proxy_manager.stop_proxy()
    
    async def _download_web_music(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Метод 1: YouTube Music Web Client"""
        temp_path = str(target_path).replace(".mp3", "_webmusic")
        opts = self._get_base_opts(temp_path)
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['web_music'],
            }
        }
        url = f"https://music.youtube.com/watch?v={video_id}"
        return await self._execute_download(opts, url, target_path, temp_path, track_info)

    async def _download_android_music(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Метод 2: Android Music Client (обычно работает лучше)"""
        temp_path = str(target_path).replace(".mp3", "_android")
        opts = self._get_base_opts(temp_path)
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android_music', 'android'],
            }
        }
        url = f"https://www.youtube.com/watch?v={video_id}"
        return await self._execute_download(opts, url, target_path, temp_path, track_info)

    async def _download_mweb(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Метод 3: Mobile Web Client"""
        temp_path = str(target_path).replace(".mp3", "_mweb")
        opts = self._get_base_opts(temp_path)
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['mweb'],
            }
        }
        url = f"https://m.youtube.com/watch?v={video_id}"
        return await self._execute_download(opts, url, target_path, temp_path, track_info)

    async def _download_tv(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Метод 4: TV HTML5 Client"""
        temp_path = str(target_path).replace(".mp3", "_tv")
        opts = self._get_base_opts(temp_path)
        opts['extractor_args'] = {
            'youtube': {
                'player_client': ['tv', 'tv_embedded'],
            }
        }
        url = f"https://www.youtube.com/watch?v={video_id}"
        return await self._execute_download(opts, url, target_path, temp_path, track_info)

    async def _download_default(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Метод 5: Дефолтный клиент (без указания)"""
        temp_path = str(target_path).replace(".mp3", "_default")
        opts = self._get_base_opts(temp_path)
        # Без extractor_args - пусть yt-dlp сам выберет лучший вариант
        url = f"https://www.youtube.com/watch?v={video_id}"
        return await self._execute_download(opts, url, target_path, temp_path, track_info)

    async def _execute_download(self, opts: dict, url: str, target_path: Path, 
                                 temp_path: str, track_info: TrackInfo) -> DownloadResult:
        """Выполнить скачивание и обработать результат"""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(opts, url))
            
            possible_paths = [
                Path(temp_path + ".mp3"),
                Path(temp_path),
            ]
            
            for result_path in possible_paths:
                if result_path.exists() and result_path.stat().st_size > 10000:
                    if result_path != target_path:
                        if target_path.exists():
                            target_path.unlink()
                        result_path.rename(target_path)
                    return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            
            for p in possible_paths:
                if p.exists():
                    p.unlink()
            
            return DownloadResult(success=False, error_message="Download produced no valid file")
        except Exception as e:
            # This handles errors within _run_yt_dlp, like network issues or yt-dlp crashes
            logger.error(f"Exception during _execute_download for {url}: {e}")
            return DownloadResult(success=False, error_message=str(e))


    def _run_yt_dlp(self, opts: dict, url: str):
        """Синхронный запуск yt-dlp"""
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
