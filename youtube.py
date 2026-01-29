import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional
import tempfile
import os

import yt_dlp
from config import Settings
from models import DownloadResult, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

# --- ВСТРОЕННЫЕ COOKIES ---
# Пользователь предоставил эти cookies для обхода блокировок YouTube
# Они будут записаны во временный файл при каждой загрузке
EMBEDDED_COOKIES = """
# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.youtube.com	TRUE	/	TRUE	1802889755	__Secure-YENID	12.YTE=hx5sGrpv4cXAPIdRFHXd34LEl9xs6SHOVZSey23ZM_rK8uwcQOTbvBKYvdhlZKKnZBlni0g4bkGEilhIN3AvbkwpPguW7x7wgwXTOUaWdayc43h09G4xjNN4x8K-2pu0gT1bBAoigedf-lUVJxdLmy8lTnm1TEst25ObhR0QhgerS3Ze11ugbDhqglgW4FsgP8Hymi6cbP3KAr9OodLvf5EKtQtChgYRCSflY5w5dxA_f5SG5vNdlBB995LUlfoxolBVq0hbpINk14mf4fGlyxF98D-tt8W586pmrf4O3Sz_mQ4qMZhhljx142X9lP0U22Fc0RI49wUDVzG3Pj2PQA
.youtube.com	TRUE	/	TRUE	1800297767	__Secure-1PSIDTS	sidts-CjUB7I_69IHVTsEmFz1bCc8xokQd0y6vYGm618UAvS418HpOuJKX-ndtW67qBA9B33xNH985nBAA
.youtube.com	TRUE	/	TRUE	1800297767	__Secure-3PSIDTS	sidts-CjUB7I_69IHVTsEmFz1bCc8xokQd0y6vYGm618UAvS418HpOuJKX-ndtW67qBA9B33xNH985nBAA
.youtube.com	TRUE	/	TRUE	1803321767	__Secure-3PAPISID	89U8_gyhKcXDzcib/A1-Vt9yNn9oSRZygJ
.youtube.com	TRUE	/	TRUE	1803321767	__Secure-3PSID	g.a0005wg1weQk7STdWGicsjnYiTTdFzmTTkqs14mb-SHwtV8vdeFmETZztwpbJwGDESXmV-TuOgACgYKATESARISFQHGX2MidFTQnAH0Z8xndlt-4XyO5BoVAUF8yKp8N9EPzOTmEkHxNegoBKVs0076
.youtube.com	TRUE	/	TRUE	1803321773	LOGIN_INFO	AFmmF2swRQIhAJRlETkGGLJyhEtuDS_ctN40_l9gjlZ4Q9mndXMZQjWzAiB3dHWvJTuaPhgmvzMC5QPOvD91WtO6TeklQMl0ibfrWQ:QUQ3MjNmeHZ4anFoOU92Q20yTDNMNlZScGNhSkN3ZV9nX1N4VmttclB2NTNvaDM0ZDJ0dHJBZ05BNXRwUEtHMl9OTThOUVFndkdaSUdyT3Y4dkZqZEpzbHhBamtMd2Z3T016Q2VnWS1yd09QQzNQdGtQZjducDVrSm9nRWtiWDU2Z3VZTW9VVEkySkQ0NndVVl84UnZxR3JEaUZ6a0wzaW1R
.youtube.com	TRUE	/	TRUE	1804103286	PREF	f6=40000000&tz=Europe.Moscow
.youtube.com	TRUE	/	TRUE	1801079295	__Secure-3PSIDCC	AKEyXzU2BU9SjkAdW_O2fm7bSWnPIp3Wirc6RkHq50SfqpsBjbExHhci8-X9g5DNEm-WgtitrQ
.youtube.com	TRUE	/	TRUE	0	YSC	JQFmKIGkkXc
.youtube.com	TRUE	/	TRUE	1785095257	__Secure-ROLLOUT_TOKEN	CO7Kpdm_1ZLlKBD15bqG35WSAxiRxISqvqySAw%3D%3D
.youtube.com	TRUE	/	TRUE	1785095293	VISITOR_INFO1_LIVE	qc1rFijKg1c
.youtube.com	TRUE	/	TRUE	1785095293	VISITOR_PRIVACY_METADATA	CgJSVRIEGgAgMA%3D%3D
"""

class YouTubeDownloader:
    """
    🛡️ Titanium Downloader v23 (Dynamic Cookies Edition).
    """
    
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.semaphore = asyncio.Semaphore(2) # Снижаем нагрузку, чтобы не злить YT

    async def search(self, query: str, limit: int = 10) -> List[TrackInfo]:
        opts = {
            'quiet': True,
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        
        loop = asyncio.get_running_loop()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch{limit}:{query}", download=False))
            
            results = []
            if info:
                entries = info.get('entries', [])
                for entry in entries:
                    if entry and entry.get('id'):
                        results.append(TrackInfo.from_yt_info(entry))
            return results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 5000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)

        async with self.semaphore:
            logger.info(f"🛡️ Starting stealth download for {video_id} with dynamic cookies...")
            return await self._download_direct(video_id, track_info)

    async def _download_direct(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        temp_path = self._settings.DOWNLOADS_DIR / f"{video_id}_temp"
        cookie_file = None

        try:
            # --- Создаем временный файл с cookies ---
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as cf:
                cf.write(EMBEDDED_COOKIES)
                cookie_file_path = cf.name
            
            logger.info(f"Using temporary cookie file: {cookie_file_path}")

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(temp_path),
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'cookiefile': cookie_file_path,  # Используем созданный файл
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['webpage', 'configs', 'js'],
                    }
                },
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }

            loop = asyncio.get_running_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await loop.run_in_executor(None, ydl.download, [f"https://www.youtube.com/watch?v={video_id}"])
            
            mp3_path = Path(f"{str(temp_path)}.mp3")
            
            if mp3_path.exists() and mp3_path.stat().st_size > 10000:
                logger.info(f"✅ Download success: {video_id}")
                target_path = self._settings.DOWNLOADS_DIR / f"{track_info.identifier}.mp3"
                mp3_path.rename(target_path)
                return DownloadResult(success=True, file_path=target_path, track_info=track_info)
            else:
                 raise ValueError("Downloaded file is too small or missing after conversion.")

        except Exception as e:
            logger.error(f"❌ Download failed for {video_id}: {e}")
            return DownloadResult(success=False, error_message=str(e))
        finally:
            # --- Гарантированно удаляем временный файл ---
            if cookie_file_path and os.path.exists(cookie_file_path):
                try:
                    os.remove(cookie_file_path)
                    logger.info(f"Removed temporary cookie file: {cookie_file_path}")
                except OSError as e:
                    logger.error(f"Failed to remove temporary cookie file {cookie_file_path}: {e}")
