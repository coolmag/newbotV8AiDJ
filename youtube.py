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
from proxy_manager import ProxyManager # <--- ДОБАВЛЕНО

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v21 (Multi-layered Defense).
    Strategy:
    1. Cache Check: Look for pre-downloaded files.
    2. API Extractors: Try to get direct links from Piped/Invidious/Cobalt.
    3. Proxied yt-dlp: Fallback to direct download using a proxy pool.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        # --- Инициализация менеджера прокси ---
        self._proxy_manager = ProxyManager(project_root=self._settings.BASE_DIR)
        
        logger.info(f"🛡️ Titanium v21 (Multi-layered). Extractors ready. Proxies loaded: {len(self._proxy_manager._proxies)}")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        cache_key = f"yt_search_v12:{query}:{limit}"
        cached = await self._cache.get(cache_key)
        if cached:
            return cached

        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        opts = {'quiet': True, 'extract_flat': True, 'skip_download': True, 'ignoreerrors': True}
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
            
            results = []
            if info:
                entries = info.get('entries', []) if 'entries' in info else [info]
                for entry in entries:
                    if not entry or not entry.get('id') or int(entry.get('duration') or 0) > 1500:
                        continue
                    
                    track = TrackInfo.from_yt_info(entry)
                    if track:
                        results.append(track)

            if results:
                await self._cache.set(cache_key, results, ttl=3600) # Кэшируем на 1 час
            return results
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        # 1. Проверка на наличие готового файла
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            logger.info(f"✅ Cache hit for {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            # 2. Попытка скачивания через API-экстракторы
            logger.info(f"🔷 Trying API extractors for {video_id}...")
            extractor_res = await self._try_api_extractors(video_id, track_info)
            if extractor_res.success:
                return await self._post_process(extractor_res)
            
            # 3. Фолбэк на прямое скачивание через yt-dlp с прокси
            logger.warning(f"🔶 API extractors failed. Falling back to proxied yt-dlp for {video_id}...")
            yt_dlp_res = await self._try_yt_dlp_direct(video_id, track_info)
            if yt_dlp_res.success:
                return await self._post_process(yt_dlp_res)

        logger.error(f"❌ All download methods failed for {video_id}.")
        return DownloadResult(success=False, error_message="All available download methods failed.", track_info=track_info)

    async def _download_from_url(self, url: str, temp_path: Path) -> bool:
        """Вспомогательная функция для скачивания файла по URL."""
        async with httpx.AsyncClient(timeout=120.0, verify=False, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(8192):
                        f.write(chunk)
                return temp_path.stat().st_size > 10000

    async def _try_api_extractors(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_temp.audio"
        
        # --- Стратегия 1: Piped (получение прямых ссылок) ---
        piped_instances = list(self._settings.PIPED_INSTANCES or [])
        random.shuffle(piped_instances)
        for url in piped_instances:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{url}/streams/{video_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        audio_streams = sorted([s for s in data.get('audioStreams', []) if s.get('mimeType') == 'audio/mp4'], key=lambda s: s.get('bitrate', 0), reverse=True)
                        if audio_streams and await self._download_from_url(audio_streams[0]['url'], temp_path):
                            logger.info(f"✅ Success via Piped: {url}")
                            return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
            except Exception:
                continue

        # --- Стратегия 2: Cobalt (как у вас и было) ---
        cobalt_instances = list(self._settings.COBALT_INSTANCES or [])
        random.shuffle(cobalt_instances)
        for url in cobalt_instances:
            try:
                headers = {"Accept": "application/json", "Content-Type": "application/json"}
                payload = {"url": f"https://www.youtube.com/watch?v={video_id}", "isAudioOnly": True}
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(f"{url}/api/json", json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('status') == 'stream' and await self._download_from_url(data['url'], temp_path):
                            logger.info(f"✅ Success via Cobalt: {url}")
                            return DownloadResult(success=True, file_path=temp_path, track_info=track_info)
            except Exception:
                continue
                
        return DownloadResult(success=False)

    async def _try_yt_dlp_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        proxy = self._proxy_manager.get_proxy()
        if not proxy:
            logger.error("🚫 No working proxies available for yt-dlp.")
            return DownloadResult(success=False, error_message="No proxies available.")

        temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_temp_dlp.mp3"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(temp_path),
            'proxy': proxy,
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
        }

        try:
            loop = asyncio.get_running_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await loop.run_in_executor(None, ydl.download, [f"https://www.youtube.com/watch?v={video_id}"])
            
            final_path = temp_path.with_suffix(".mp3")
            if final_path.exists() and final_path.stat().st_size > 10000:
                logger.info(f"✅ Success via yt-dlp with proxy: {proxy}")
                return DownloadResult(success=True, file_path=final_path, track_info=track_info)
            else:
                raise ValueError("Downloaded file is too small or missing.")

        except Exception as e:
            logger.error(f"❌ yt-dlp failed with proxy {proxy}: {e}")
            self._proxy_manager.report_dead_proxy(proxy) # Сообщаем, что прокси "мертв"
            return DownloadResult(success=False, error_message=f"yt-dlp error: {e}")

    async def _post_process(self, result: DownloadResult) -> DownloadResult:
        """Переименовывает временный файл в постоянный."""
        if not result.success or not result.file_path:
            return result
        
        target_path = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        
        try:
            # Если файл уже существует, удаляем его перед переименованием
            if target_path.exists():
                target_path.unlink()
            
            # Переименовываем временный файл
            result.file_path.rename(target_path)
            result.file_path = target_path
        except Exception as e:
            logger.error(f"Failed to post-process file {result.file_path}: {e}")
            # Если не удалось переименовать, удаляем временный файл
            try:
                result.file_path.unlink()
            except OSError:
                pass
            return DownloadResult(success=False, error_message="File processing failed.")
            
        return result
