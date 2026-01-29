import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

import httpx
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v32 (Pure Piped API).
    Bypasses YouTube IP blocks by using Piped instances as proxies.
    No yt-dlp dependencies for network operations.
    """
    
    # Список инстансов Piped. 
    # Важно: Мы используем те, что поддерживают "proxying" (проксирование трафика).
    PIPED_INSTANCES = [
        "https://piped-api.lunar.icu",       # Твой вариант
        "https://pipedapi.adminforge.de",    # Немецкий, надежный
        "https://api-piped.mha.fi",          # Финский
        "https://piped-api.codespace.cz",    # Чешский
        "https://api.piped.privacy.com.de",  # Еще один немецкий
        "https://pipedapi.drgns.space",
        "https://pipedapi.kavin.rocks",      # Старый, может быть заблочен, но пусть будет
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        # Piped быстрый, можно 3 потока
        self.semaphore = asyncio.Semaphore(3)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """Поиск через Piped API (без yt-dlp)"""
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Перемешиваем, чтобы распределить нагрузку
            instances = self.PIPED_INSTANCES.copy()
            random.shuffle(instances)

            for instance in instances:
                try:
                    # Запрос к API поиска Piped
                    resp = await client.get(f"{instance}/search", params={"q": query, "filter": "music_songs"})
                    if resp.status_code != 200: continue
                    
                    data = resp.json()
                    items = data.get('items', [])
                    results = []
                    
                    for item in items[:limit]:
                        # Piped возвращает URL как "/watch?v=ID"
                        vid_url = item.get('url', '')
                        vid_id = vid_url.split('v=')[-1] if 'v=' in vid_url else ''
                        
                        if not vid_id: continue
                        if item.get('duration', 0) > 900: continue # Фильтр 15 мин

                        track = TrackInfo(
                            identifier=vid_id,
                            title=item.get('title'),
                            uploader=item.get('uploaderName'),
                            duration=item.get('duration', 0),
                            thumbnail_url=item.get('thumbnail'),
                            source="piped"
                        )
                        results.append(track)
                    
                    if results:
                        return results # Если нашли на одном инстансе, возвращаем
                        
                except Exception as e:
                    logger.warning(f"Search failed on {instance}: {e}")
                    continue
        
        return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        
        # Проверка кэша
        if final_path.exists() and final_path.stat().st_size > 10000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            return await self._download_piped(video_id, final_path, track_info)

    async def _download_piped(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        """Скачивание аудиопотока через Piped"""
        
        instances = self.PIPED_INSTANCES.copy()
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            for instance in instances:
                try:
                    logger.info(f"🧪 Trying Piped Instance: {instance} for {video_id}")
                    
                    # 1. Получаем информацию о потоках
                    resp = await client.get(f"{instance}/streams/{video_id}")
                    if resp.status_code != 200: 
                        logger.warning(f"Instance {instance} returned {resp.status_code}")
                        continue
                        
                    data = resp.json()
                    audio_streams = data.get('audioStreams', [])
                    
                    if not audio_streams:
                        logger.warning(f"No audio streams on {instance}")
                        continue
                        
                    # 2. Выбираем лучший поток (m4a обычно стабильнее)
                    # Сортируем по битрейту
                    best_stream = sorted(audio_streams, key=lambda x: x.get('bitrate', 0), reverse=True)[0]
                    stream_url = best_stream.get('url')
                    
                    if not stream_url: continue

                    # 3. Скачиваем сам файл
                    logger.info(f"⬇️ Downloading stream from {instance}...")
                    
                    temp_path = str(target_path).replace(".mp3", "_temp")
                    
                    async with client.stream("GET", stream_url) as stream_resp:
                        if stream_resp.status_code == 200:
                            with open(temp_path, "wb") as f:
                                async for chunk in stream_resp.aiter_bytes(chunk_size=8192):
                                    f.write(chunk)
                                    
                    # 4. Проверка и переименование
                    temp_file = Path(temp_path)
                    if temp_file.exists() and temp_file.stat().st_size > 10000:
                        if temp_file != target_path:
                            temp_file.rename(target_path)
                        
                        logger.info(f"✅ Success via Piped: {instance}")
                        return DownloadResult(success=True, file_path=target_path, track_info=track_info)
                    
                except Exception as e:
                    logger.warning(f"❌ Error on {instance}: {e}")
                    continue

        return DownloadResult(success=False, error_message="All Piped instances failed.")
