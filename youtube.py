from __future__ import annotations
import asyncio
import logging
import os
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
import httpx
import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    """
    ADAPTER: CERBERUS ULTIMATE - Fix for format availability issues
    - Ultra-permissive format selection
    - Multiple fallback strategies
    - Aggressive retry logic
    """
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self._settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        self.cookies_path = Path("cookies/youtube_railway.txt")
        cookies_content = os.getenv("YT_COOKIES_CONTENT") or os.getenv("COOKIES_CONTENT")
        if cookies_content:
            try:
                self.cookies_path.parent.mkdir(exist_ok=True)
                with open(self.cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                logger.info("🍪 Cookies loaded.")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)

        self.search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": 20,
            "retries": 3,
        }
        
        self.ytdlp_formats = [
            {"format": "bestaudio/best", "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]},
            {"format": "bestaudio[ext=m4a]/bestaudio", "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]},
            {"format": "bestaudio[ext=webm]/bestaudio", "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]},
            {"format": "bestaudio[asr>0]/bestaudio/best", "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]}
        ]

        self.base_opts = {
            "quiet": True, "no_warnings": True,
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "keepvideo": False, "socket_timeout": 60, "retries": 15, "ignoreerrors": True, 'nocheckcertificate': True,
            "proxy": os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or "",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
            },
        }

        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            self.base_opts['cookiefile'] = str(self.cookies_path)
            logger.info("Cookie file applied.")

        logger.info("🟢 YouTube 'Cerberus Ultimate' Engine initialized.")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip()
        if "audio" not in clean_query: search_text = f"{clean_query} audio"
        else: search_text = clean_query
        cache_key = f"yt_search_cerberus:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached
        
        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            def do_search():
                with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                    try: return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception: return None
            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=25.0)
            except asyncio.TimeoutError: return []
            
            results = []
            if res and 'entries' in res:
                for entry in res.get('entries', []):
                    if not entry: continue
                    results.append(TrackInfo(
                        identifier=str(entry.get('id', '')), title=entry.get('title', 'Unknown'),
                        artist=entry.get('channel', 'Unknown'), duration=int(entry.get('duration') or 0),
                        source=Source.YOUTUBE))
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown Track", artist="Web Player", duration=0, source=Source.YOUTUBE)

        if not video_id or video_id.startswith('--') or len(video_id) < 8:
            return DownloadResult(success=False, error_message="Invalid video ID", track_info=track_info)

        cached_file_id = await self._cache.get(f"file_id:{video_id}")
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)

        final_path_mp3 = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path_mp3.exists() and final_path_mp3.stat().st_size > 10000:
             return DownloadResult(success=True, file_path=final_path_mp3, track_info=track_info)
        
        result = await self._download_piped(video_id, track_info)
        if not result.success: result = await self._download_ytdlp_with_retry(video_id, track_info)
        if not result.success: result = await self._download_direct(video_id, track_info)
        
        if result.success and result.file_path and result.file_path.suffix != ".mp3":
            result = await self._run_ffmpeg_postprocessor(result.file_path, track_info)

        if result.success and result.file_path:
            await self._cache.set(f"file_id:{video_id}", video_id, ttl=86400)
        
        return result

    async def _download_piped(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        piped_instances = self._settings.PIPED_INSTANCE_LIST
        random.shuffle(piped_instances)
        async with httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_connections=10), follow_redirects=True) as client:
            for instance in piped_instances:
                try:
                    logger.info(f"Trying Piped instance: {instance} for {video_id}")
                    info_url = f"{instance}/streams/{video_id}"
                    info_resp = await client.get(info_url, follow_redirects=True)
                    info_resp.raise_for_status()
                    data = info_resp.json()
                    if data.get("error"): logger.warning(f"Video {video_id} error on {instance}: {data.get('error')}"); continue
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams: logger.warning(f"No audio streams for {video_id} on {instance}"); continue
                    audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                    for stream in audio_streams[:3]:
                        try:
                            audio_url = stream.get("url")
                            if not audio_url: continue
                            file_ext = stream.get("format", "webm").lower()
                            if file_ext == "m4a": file_ext = "mp4"
                            file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.{file_ext}"
                            async with client.stream("GET", audio_url, timeout=60) as response:
                                response.raise_for_status()
                                with file_path.open("wb") as f:
                                    async for chunk in response.aiter_bytes(chunk_size=16384): f.write(chunk)
                            if file_path.exists() and file_path.stat().st_size > 5000:
                                logger.info(f"Piped download successful: {video_id} from {instance}")
                                return DownloadResult(success=True, file_path=file_path, track_info=track_info)
                        except Exception as e: logger.warning(f"Failed to download stream {stream.get('format')}: {e}"); continue
                except Exception as e: logger.warning(f"Piped instance {instance} failed: {e}"); continue
        return DownloadResult(success=False, error_message="All Piped instances failed", track_info=track_info)

    async def _download_ytdlp_with_retry(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        for i, format_strategy in enumerate(self.ytdlp_formats):
            logger.info(f"Trying yt-dlp strategy {i + 1} for {video_id}")
            opts = {**self.base_opts, **format_strategy}
            if i == 1:
                opts["extractor_args"] = {"youtube": {"player_client": ["android_music"]}}
                opts["http_headers"]["User-Agent"] = "com.google.android.apps.youtube.music/6.21.51"
            async with self.semaphore:
                loop = asyncio.get_running_loop()
                def do_download():
                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
                        return True
                    except Exception as e:
                        logger.warning(f"yt-dlp download error (strategy {i + 1}): {e}")
                        return False
                try:
                    if await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=120.0):
                        result = await self._wait_for_file(video_id, track_info)
                        if result.success: return result
                except asyncio.TimeoutError:
                    logger.warning(f"yt-dlp strategy {i + 1} timeout for {video_id}")
                    continue
        return DownloadResult(success=False, error_message="All yt-dlp strategies failed", track_info=track_info)

    async def _download_direct(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        opts = {**self.base_opts, "format": "best", "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}], "force_generic_extractor": True}
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
                    return True
                except Exception as e: logger.error(f"Direct download failed: {e}"); return False
            try:
                if await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=180.0):
                    return await self._wait_for_file(video_id, track_info)
            except asyncio.TimeoutError:
                logger.error(f"Direct download timeout for {video_id}")
        return DownloadResult(success=False, error_message="Direct download failed", track_info=track_info)

    async def _run_ffmpeg_postprocessor(self, input_path: Path, track_info: Optional[TrackInfo]) -> DownloadResult:
        if not input_path.exists(): return DownloadResult(success=False, error_message="Input file not found", track_info=track_info)
        output_path = input_path.with_suffix(".mp3")
        if input_path.suffix.lower() == '.mp3': return DownloadResult(success=True, file_path=input_path, track_info=track_info)
        try:
            proc = await asyncio.create_subprocess_exec('ffmpeg','-i',str(input_path),'-y','-codec:a','libmp3lame','-q:a','3','-ac','2','-ar','44100',str(output_path),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            if proc.returncode == 0:
                try: input_path.unlink()
                except OSError: pass
                if output_path.exists() and output_path.stat().st_size > 10000:
                    return DownloadResult(success=True, file_path=output_path, track_info=track_info)
            logger.warning(f"FFmpeg failed, trying alternative for {input_path}")
            return await self._convert_with_ffmpeg_alternative(input_path, track_info)
        except Exception as e:
            logger.error(f"FFmpeg execution error: {e}")
            return DownloadResult(success=False, error_message="FFmpeg execution error", track_info=track_info)

    async def _convert_with_ffmpeg_alternative(self, input_path: Path, track_info: TrackInfo) -> DownloadResult:
        output_path = input_path.with_suffix(".mp3")
        try:
            cmd = ['ffmpeg', '-i', str(input_path), '-y', '-f', 'mp3', str(output_path)]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 10000:
                try: input_path.unlink()
                except: pass
                return DownloadResult(success=True, file_path=output_path, track_info=track_info)
        except Exception as e: logger.error(f"Alternative FFmpeg also failed: {e}")
        return DownloadResult(success=False, error_message="Audio conversion failed", track_info=track_info)

    async def _wait_for_file(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        start_wait = time.time(); extensions = ['.mp3', '.webm', '.m4a', '.opus', '.mp4', '.ogg', '.flac', '.wav', '.aac']
        while time.time() - start_wait < 30:
            for ext in extensions:
                path = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
                if path.exists():
                    file_size = path.stat().st_size
                    if file_size > 5000:
                        logger.info(f"Found downloaded file: {path} ({file_size} bytes)")
                        return DownloadResult(success=True, file_path=path, track_info=track_info)
                    elif file_size > 0: await asyncio.sleep(0.5)
            await asyncio.sleep(1)
        return DownloadResult(success=False, error_message="File not found after download", track_info=track_info)