import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import httpx
import yt_dlp
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v28 (API Swarm Edition).
    Strategy: Bypass Railway IP blocks by using public API instances (Cobalt/Piped).
    Direct yt-dlp is ONLY a search engine here.
    """
    
    # Список публичных инстансов (Cobalt и Piped)
    # Эти серверы принимают удар YouTube на себя
    API_INSTANCES = [
        # Cobalt Instances (Best for MP3)
        "https://api.cobalt.tools",
        "https://cobalt.xy24.eu.org",
        "https://cobalt.slpy.one",
        "https://cobalt.kwiatekmiki.pl",
        "https://cobalt.armadyne.net",
        
        # Piped Instances (Backups)
        "https://pipedapi.kavin.rocks",
        "https://api.piped.yt",
        "https://pipedapi.moomoo.me",
        "https://piped-api.garudalinux.org",
        "https://pa.il.ax",
        "https://pipedapi.smnz.de",
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        # Ограничиваем многопоточность, чтобы не забивать канал
        self.semaphore = asyncio.Semaphore(2)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Поиск остается через yt-dlp, так как он легкий и редко банится."""
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"
            
        opts = {
            'quiet': True,
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android']}}
        }
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch{limit}:{query}", download=False))
            
            results = []
            if info:
                entries = info.get('entries', [])
                for entry in entries:
                    if entry.get('duration') and entry.get('duration') > 900: # Фильтр 15 мин
                        continue
                    if entry and entry.get('id'):
                        results.append(TrackInfo.from_yt_info(entry))
            return results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            logger.info(f"✅ Cache hit for {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"🌩️ Swarm downloading: {video_id}")
            return await self._download_via_api_swarm(video_id, track_info)

    async def _download_via_api_swarm(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_temp"
        
        # Перемешиваем список API, чтобы нагрузка распределялась
        instances = self.API_INSTANCES.copy()
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
            for api_url in instances:
                try:
                    # Определяем тип API по URL
                    if "cobalt" in api_url:
                        success = await self._try_cobalt(client, api_url, video_id, temp_path)
                    else:
                        success = await self._try_piped(client, api_url, video_id, temp_path)
                    
                    if success:
                        # Если скачалось, обрабатываем и возвращаем
                        mp3_path = Path(str(temp_path) + ".mp3") if not str(temp_path).endswith(".mp3") else temp_path
                        
                        # Если файл сохранился без расширения, добавим .mp3
                        if temp_path.exists() and not mp3_path.exists():
                             temp_path.rename(mp3_path)
                        
                        if mp3_path.exists() and mp3_path.stat().st_size > 10000:
                            logger.info(f"✅ Download success via {api_url}")
                            target_path = self._settings.DOWNLOADS_DIR / f"{track_info.identifier}.mp3" if track_info else mp3_path
                            if mp3_path != target_path:
                                mp3_path.rename(target_path)
                            return DownloadResult(success=True, file_path=target_path, track_info=track_info)
                
                except Exception as e:
                    logger.warning(f"⚠️ API {api_url} failed: {str(e)[:50]}...")
                    continue

        return DownloadResult(success=False, error_message="All API instances failed.")

    async def _try_cobalt(self, client, base_url, video_id, save_path) -> bool:
        """Попытка скачать через Cobalt API"""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        payload = {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "aFormat": "mp3",
            "isAudioOnly": True
        }
        
        resp = await client.post(f"{base_url}/api/json", json=payload, headers=headers)
        if resp.status_code != 200:
            return False
            
        data = resp.json()
        if data.get("status") != "stream" and data.get("status") != "redirect":
            return False
            
        download_url = data.get("url")
        if not download_url:
            return False
            
        return await self._stream_to_file(client, download_url, save_path)

    async def _try_piped(self, client, base_url, video_id, save_path) -> bool:
        """Попытка скачать через Piped API"""
        resp = await client.get(f"{base_url}/streams/{video_id}")
        if resp.status_code != 200:
            return False
            
        data = resp.json()
        audio_streams = data.get("audioStreams", [])
        if not audio_streams:
            return False
            
        # Берем лучший поток m4a/mp4
        stream = sorted(audio_streams, key=lambda x: x.get("bitrate", 0), reverse=True)[0]
        return await self._stream_to_file(client, stream["url"], save_path)

    async def _stream_to_file(self, client, url, path) -> bool:
        """Скачивание потока в файл"""
        try:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return False
                with open(path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
            return True
        except Exception:
            return False
