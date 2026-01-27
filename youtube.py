import asyncio
import logging
import random
import os
import json
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
    Next-Gen Downloader (2026 Ready).
    Strategy:
    1. Cache Check
    2. Delegation (Cobalt API) -> Bypasses Railway IP blocks completely.
    3. Delegation (Piped API) -> Secondary fallback.
    4. Direct (yt-dlp with PoToken/Android Client) -> Last resort.
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Настройка Cookies и Auth
        self._setup_auth()
        
        # Семафор для ограничения нагрузки на сеть
        self.semaphore = asyncio.Semaphore(self._settings.MAX_CONCURRENT_DOWNLOADS)
        
        # Базовые настройки yt-dlp для "Direct" режима
        self.ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "ignoreerrors": True,
            # ВАЖНО: Использование Android клиента часто обходит 403 на хостингах
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web_creator"],
                    "player_skip": ["webpage", "configs", "js"],
                }
            },
            # Если есть PO_TOKEN (добавить в ENV)
            "po_token_web": self._settings.PO_TOKEN if self._settings.PO_TOKEN else None,
        }

        if self.cookies_path.exists():
            self.ydl_opts['cookiefile'] = str(self.cookies_path)

        logger.info("🚀 Next-Gen YouTube Engine Initialized")

    def _setup_auth(self):
        """Загрузка Cookies из ENV (Railway friendly)"""
        self.cookies_path = Path("cookies.txt")
        cookies_content = self._settings.COOKIES_CONTENT
        if cookies_content:
            try:
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies loaded from ENV.")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """
        Поиск. Используем yt-dlp 'extract_flat' - это быстро и редко блокируется.
        """
        cache_key = f"search_v2:{query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached

        logger.info(f"🔎 Searching: {query}")
        
        # Формируем поисковый запрос
        search_query = f"ytsearch{limit}:{query}" if "http" not in query else query
        
        loop = asyncio.get_running_loop()
        
        try:
            # Используем отдельную конфигурацию для поиска (максимально легкую)
            search_opts = {
                'quiet': True, 
                'extract_flat': True, 
                'skip_download': True,
                'ignoreerrors': True
            }
            
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=False))
                
            results = []
            if info:
                entries = info.get('entries', []) if 'entries' in info else [info]
                for entry in entries:
                    if not entry: continue
                    t = TrackInfo(
                        identifier=entry.get('id'),
                        title=entry.get('title', 'Unknown'),
                        artist=entry.get('uploader') or entry.get('channel', 'Unknown'),
                        duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE
                    )
                    results.append(t)
            
            if results:
                await self._cache.set(cache_key, results, ttl=3600)
            return results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        """
        Основной метод загрузки. Реализует паттерн каскада.
        """
        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown", artist="Unknown", duration=0)

        # 1. Проверка кэша (файл уже скачан?)
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 50000:
            logger.info(f"💾 Cache hit for {video_id}")
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            # 2. Стратегия Cobalt (Делегирование) - САМАЯ НАДЕЖНАЯ В 2026
            res = await self._strategy_cobalt(video_id, track_info)
            if res.success: return await self._finalize_file(res)

            # 3. Стратегия Piped (Делегирование резерв)
            res = await self._strategy_piped(video_id, track_info)
            if res.success: return await self._finalize_file(res)

            # 4. Стратегия Direct (Локальный yt-dlp) - Крайний случай
            res = await self._strategy_direct_ytdlp(video_id, track_info)
            return await self._finalize_file(res)

    async def _strategy_cobalt(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """
        Использует API Cobalt.tools.
        Плюсы: IP сервера Railway не светится перед YouTube.
        """
        logger.info(f"🛡 Trying Cobalt strategy for {video_id}...")
        
        # Перемешиваем инстансы для балансировки
        instances = list(self._settings.COBALT_INSTANCES)
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            for base_url in instances:
                try:
                    # Cobalt API Request
                    payload = {
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "vCodec": "h264",
                        "vQuality": "480",
                        "aFormat": "mp3", # Просим сразу MP3
                        "isAudioOnly": True
                    }
                    headers = {"Accept": "application/json", "Content-Type": "application/json"}
                    
                    # 1. Запрашиваем ссылку
                    resp = await client.post(f"{base_url}/api/json", json=payload, headers=headers)
                    if resp.status_code != 200: continue
                    
                    data = resp.json()
                    download_url = data.get("url")
                    if not download_url: continue
                    
                    # 2. Скачиваем файл
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_temp.mp3"
                    async with client.stream("GET", download_url) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                                
                    if temp_path.stat().st_size > 10000:
                        logger.info(f"✅ Cobalt success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)

                except Exception as e:
                    logger.warning(f"Cobalt instance {base_url} failed: {e}")
                    continue
                    
        return DownloadResult(success=False, error_message="All Cobalt instances failed")

    async def _strategy_piped(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """
        Использует API Piped.
        """
        logger.info(f"🛡 Trying Piped strategy for {video_id}...")
        instances = list(self._settings.PIPED_INSTANCES)
        random.shuffle(instances)
        
        async with httpx.AsyncClient(timeout=20.0) as client:
            for base_url in instances:
                try:
                    # Получаем стримы
                    resp = await client.get(f"{base_url}/streams/{video_id}")
                    if resp.status_code != 200: continue
                    
                    data = resp.json()
                    audio_streams = [s for s in data.get("audioStreams", []) if s.get("url")]
                    if not audio_streams: continue
                    
                    # Берем лучший битрейт
                    best_stream = max(audio_streams, key=lambda x: x.get("bitrate", 0))
                    stream_url = best_stream["url"]
                    
                    temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_piped.mp3" # Piped обычно отдает m4a/webm, но ffmpeg потом починит
                    
                    async with client.stream("GET", stream_url) as r:
                        r.raise_for_status()
                        with open(temp_path, "wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                                
                    if temp_path.stat().st_size > 10000:
                        logger.info(f"✅ Piped success via {base_url}")
                        return DownloadResult(success=True, file_path=temp_path, track_info=track_info)

                except Exception as e:
                    continue
                    
        return DownloadResult(success=False, error_message="All Piped instances failed")

    async def _strategy_direct_ytdlp(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        """
        Локальный yt-dlp. Используем как последнее средство.
        Пытаемся эмулировать мобильный клиент.
        """
        logger.warning(f"⚠️ Falling back to direct yt-dlp for {video_id}...")
        
        loop = asyncio.get_running_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        try:
            # Копируем опции чтобы не засорять глобальные
            opts = self.ydl_opts.copy()
            
            # Попытка скачать
            with yt_dlp.YoutubeDL(opts) as ydl:
                await loop.run_in_executor(None, lambda: ydl.download([url]))
            
            # Проверяем что скачалось
            # yt-dlp может скачать как m4a, webm или mp3 в зависимости от source
            # Ищем любой файл с этим ID
            for f in self._settings.DOWNLOADS_DIR.glob(f"{video_id}.*"):
                if f.stat().st_size > 10000:
                    return DownloadResult(success=True, file_path=f, track_info=track_info)
                    
            return DownloadResult(success=False, error_message="Direct download finished but file missing")
            
        except Exception as e:
            logger.error(f"Direct download failed: {e}")
            return DownloadResult(success=False, error_message=str(e))

    async def _finalize_file(self, result: DownloadResult) -> DownloadResult:
        """
        Приводит файл к формату MP3, если он был скачан в другом формате.
        """
        if not result.success or not result.file_path:
            return result
            
        input_path = result.file_path
        target_path = self._settings.DOWNLOADS_DIR / f"{result.track_info.identifier}.mp3"
        
        # Если уже MP3 и имя правильное
        if input_path.suffix == ".mp3" and input_path.name == target_path.name:
            return result
            
        # Конвертация через FFmpeg
        try:
            logger.info(f"🔧 Converting {input_path.name} to MP3...")
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', str(input_path),
                '-vn', # no video
                '-acodec', 'libmp3lame',
                '-q:a', '4', # good quality VBR
                '-y', # overwrite
                str(target_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
            
            if target_path.exists() and target_path.stat().st_size > 0:
                # Удаляем исходник
                try: input_path.unlink()
                except: pass
                
                result.file_path = target_path
                return result
            
        except Exception as e:
            logger.error(f"Conversion error: {e}")
            # Возвращаем исходный файл, если конвертация не удалась, но файл есть
            return result
            
        return DownloadResult(success=False, error_message="Conversion failed")