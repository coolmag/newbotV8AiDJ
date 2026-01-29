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
    🛡️ Titanium Downloader v31 (Invidious API + SoundCloud).
    Uses direct API calls to Invidious instances (bypass Google).
    Fallbacks to SoundCloud if Invidious fails.
    """
    
    # Список живых инстансов Invidious (2026)
    # Мы будем перебирать их по очереди
    INVIDIOUS_INSTANCES = [
        "https://inv.nadeko.net",
        "https://invidious.nerdvpn.de",
        "https://inv.tux.pizza",
        "https://invidious.drgns.space",
        "https://iv.melmac.space",
        "https://yewtu.be",             # Часто блочат, но попробуем
        "https://vid.puffyan.us",
    ]

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(3)

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """
        1. Ищем на Invidious (это YouTube контент).
        2. Если не вышло - ищем на SoundCloud.
        """
        if kwargs.get('decade'):
            query = f"{query} {kwargs['decade']}"

        # --- Попытка 1: Invidious API ---
        inv_results = await self._search_invidious(query, limit)
        if inv_results:
            return inv_results
            
        # --- Попытка 2: SoundCloud (Резерв) ---
        logger.info("Invidious failed, switching to SoundCloud search...")
        return await self._search_soundcloud(query, limit)

    async def _search_invidious(self, query: str, limit: int) -> List[TrackInfo]:
        async with httpx.AsyncClient(timeout=6.0) as client:
            random.shuffle(self.INVIDIOUS_INSTANCES)
            for instance in self.INVIDIOUS_INSTANCES:
                try:
                    resp = await client.get(f"{instance}/api/v1/search", params={"q": query, "type": "video"})
                    if resp.status_code != 200: continue
                    
                    data = resp.json()
                    results = []
                    for item in data[:limit]:
                        # Фильтр длины (15 мин)
                        if item.get('lengthSeconds', 0) > 900: continue
                        
                        results.append(TrackInfo(
                            identifier=item.get('videoId'),
                            title=item.get('title'),
                            uploader=item.get('author'),
                            duration=item.get('lengthSeconds'),
                            thumbnail_url=item.get('videoThumbnails', [{}])[0].get('url'),
                            source="invidious" # Пометка источника
                        ))
                    if results:
                        return results
                except Exception:
                    continue
        return []

    async def _search_soundcloud(self, query: str, limit: int) -> List[TrackInfo]:
        # Старый добрый поиск через yt-dlp для SoundCloud
        try:
            loop = asyncio.get_running_loop()
            opts = {'quiet': True, 'extract_flat': True, 'skip_download': True, 'ignoreerrors': True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"scsearch{limit}:{query}", download=False))
                
            results = []
            if info:
                for entry in info.get('entries', []):
                    if entry:
                        results.append(TrackInfo(
                            identifier=entry.get('url'),
                            title=entry.get('title'),
                            uploader=entry.get('uploader'),
                            duration=int(entry.get('duration', 0)),
                            source="soundcloud"
                        ))
            return results
        except Exception:
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id[-10:]}.mp3" # Короткое имя
        
        if final_path.exists() and final_path.stat().st_size > 10000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            if track_info and track_info.source == "soundcloud":
                return await self._download_soundcloud(video_id, final_path, track_info)
            else:
                # Если источник не указан или invidious -> пробуем API
                return await self._download_invidious(video_id, final_path, track_info)

    async def _download_invidious(self, video_id: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        logger.info(f"👽 Trying Invidious API for {video_id}...")
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            random.shuffle(self.INVIDIOUS_INSTANCES)
            
            for instance in self.INVIDIOUS_INSTANCES:
                try:
                    # 1. Получаем инфо о видео
                    resp = await client.get(f"{instance}/api/v1/videos/{video_id}")
                    if resp.status_code != 200: continue
                    
                    data = resp.json()
                    
                    # 2. Ищем аудио поток (как в твоем примере)
                    audio_url = None
                    adaptive = data.get('adaptiveFormats', [])
                    # Сортируем по битрейту (лучшее качество)
                    adaptive.sort(key=lambda x: int(x.get('bitrate', 0)), reverse=True)
                    
                    for fmt in adaptive:
                        if "audio" in fmt.get('type', ''):
                            audio_url = fmt.get('url')
                            break
                    
                    if not audio_url: continue

                    # 3. Скачиваем поток
                    logger.info(f"Stream found on {instance}, downloading...")
                    async with client.stream("GET", audio_url) as response:
                        if response.status_code == 200:
                            with open(target_path, "wb") as f:
                                async for chunk in response.aiter_bytes(chunk_size=8192):
                                    f.write(chunk)
                            
                            if target_path.stat().st_size > 10000:
                                logger.info(f"✅ Success via Invidious: {instance}")
                                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
                
                except Exception as e:
                    logger.warning(f"Instance {instance} failed: {e}")
                    continue

        return DownloadResult(success=False, error_message="All Invidious instances failed.")

    async def _download_soundcloud(self, url: str, target_path: Path, track_info: TrackInfo) -> DownloadResult:
        # Для SoundCloud используем yt-dlp, он там работает отлично
        try:
            loop = asyncio.get_running_loop()
            temp_path = str(target_path).replace(".mp3", "")
            opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_path, # yt-dlp сам добавит .mp3
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}],
            }
            await loop.run_in_executor(None, lambda: self._run_yt_dlp(opts, url))
            
            # Проверяем, какой файл создался (иногда добавляется расширение)
            created_path = Path(temp_path + ".mp3")
            if created_path.exists():
                if created_path != target_path:
                    created_path.rename(target_path)
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
        except Exception:
            pass
        return DownloadResult(success=False)

    def _run_yt_dlp(self, opts, url):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])