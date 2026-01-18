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
    ADAPTER: NUCLEAR OPTION - Maximum compatibility
    - Skip problematic video IDs
    - Multiple fallback methods
    - Direct file download if all else fails
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
            "ignoreerrors": True,
        }

        self.problematic_prefixes = ['--', 'n--', 'ytr', 'yt-']
        
        self.base_ytdlp_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "keepvideo": False,
            "socket_timeout": 60,
            "retries": 20,
            "ignoreerrors": True,
            'nocheckcertificate': True,
            "no_color": True,
            "extractor_retries": 3,
            "fragment_retries": 10,
            "skip_unavailable_fragments": True,
            "hls_prefer_native": True,
        }

        self.sabr_bypass_extractor_args = {
            "youtube": {
                "player_client": ["tv_embedded", "web_creator", "android_music"],
                "player_skip": ["webpage"],
            }
        }
        self.sabr_bypass_http_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
            self.base_ytdlp_opts['cookiefile'] = str(self.cookies_path)
            logger.info("Cookie file applied.")

        logger.info("🟢 YouTube 'Nuclear Option' Engine initialized.")

    def is_problematic_video_id(self, video_id: str) -> bool:
        if len(video_id) < 8 or any(video_id.startswith(p) for p in self.problematic_prefixes) or video_id.count('-') > 2:
            return True
        return False

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        clean_query = query.lower().strip(); search_text = f"{clean_query} audio" if "audio" not in clean_query else clean_query
        cache_key = f"yt_search_nuclear:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached
        
        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            def do_search():
                with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                    try: return ydl.extract_info(f"ytsearch{limit}:{search_text}", download=False)
                    except Exception: return None
            try:
                res = await asyncio.wait_for(loop.run_in_executor(None, do_search), timeout=30.0)
            except asyncio.TimeoutError: return []
            
            results = []
            if res and 'entries' in res:
                for entry in res.get('entries', []):
                    if not entry: continue
                    video_id = str(entry.get('id', ''))
                    if self.is_problematic_video_id(video_id): continue
                    results.append(TrackInfo(identifier=video_id, title=entry.get('title', 'Unknown'), artist=entry.get('channel', 'Unknown'), duration=int(entry.get('duration') or 0), source=Source.YOUTUBE))
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown Track", artist="Web Player", duration=0, source=Source.YOUTUBE)
        if self.is_problematic_video_id(video_id):
            return DownloadResult(success=False, error_message=f"Unsupported video ID: {video_id}", track_info=track_info)

        cached_file_id = await self._cache.get(f"file_id:{video_id}")
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)
        
        final_path_mp3 = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path_mp3.exists() and final_path_mp3.stat().st_size > 10000:
             return DownloadResult(success=True, file_path=final_path_mp3, track_info=track_info)
        
        result = await self._download_piped_fast(video_id, track_info)
        if not result.success: result = await self._download_ytdlp_aggressive(video_id, track_info)
        if not result.success: result = await self._download_any_audio(video_id, track_info)
        
        if result.success and result.file_path and result.file_path.suffix != ".mp3":
            result = await self._convert_to_mp3(result.file_path, track_info)
        
        if result.success and result.file_path:
            await self._cache.set(f"file_id:{video_id}", video_id, ttl=86400)
        
        return result

    async def _download_piped_fast(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        piped_instances = self._settings.PIPED_INSTANCE_LIST
        random.shuffle(piped_instances)
        async with httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=5), follow_redirects=True) as client:
            for instance in piped_instances:
                try:
                    info_resp = await client.get(f"{instance}/streams/{video_id}", timeout=10)
                    if info_resp.status_code != 200: continue
                    data = info_resp.json()
                    if data.get("error"): continue
                    audio_streams = sorted(data.get("audioStreams",[]), key=lambda x: x.get("bitrate",0), reverse=True)
                    if not audio_streams: continue
                    audio_url = audio_streams[0].get("url")
                    if not audio_url: continue
                    file_ext = audio_streams[0].get("format", "webm").lower()
                    file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.{file_ext}"
                    async with client.stream("GET", audio_url, timeout=30) as response:
                        response.raise_for_status()
                        with file_path.open("wb") as f:
                            async for chunk in response.aiter_bytes(): f.write(chunk)
                    if file_path.exists() and file_path.stat().st_size > 5000:
                        return DownloadResult(success=True, file_path=file_path, track_info=track_info)
                except Exception: continue
        return DownloadResult(success=False, error_message="Fast Piped failed", track_info=track_info)

    async def _download_ytdlp_aggressive(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        url = f"https://www.youtube.com/watch?v={video_id}"
        opts = {**self.base_ytdlp_opts, "format": "bestaudio/best", "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
                "extractor_args": self.sabr_bypass_extractor_args, "http_headers": self.sabr_bypass_http_headers}
        return await self._execute_ytdlp_download(url, opts, video_id, track_info)

    async def _download_any_audio(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        opts = {**self.base_ytdlp_opts, "format": "worst", "force_generic_extractor": True}
        return await self._execute_ytdlp_download(f"https://www.youtube.com/watch?v={video_id}", opts, video_id, track_info)

    async def _execute_ytdlp_download(self, url: str, opts: dict, video_id: str, track_info: TrackInfo) -> DownloadResult:
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
                    return True
                except Exception as e:
                    if "is not a valid URL" not in str(e): logger.warning(f"yt-dlp download error: {e}")
                    return False
            try:
                if await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=180.0):
                    return await self._wait_for_file(video_id, track_info)
            except asyncio.TimeoutError: pass
        return DownloadResult(success=False, error_message="yt-dlp execution failed", track_info=track_info)

    async def _wait_for_file(self, video_id: str, track_info: TrackInfo) -> DownloadResult:
        start_wait = time.time(); extensions = ['.mp3', '.webm', '.m4a', '.opus']
        while time.time() - start_wait < 30:
            for ext in extensions:
                path = self._settings.DOWNLOADS_DIR / f"{video_id}{ext}"
                if path.exists() and path.stat().st_size > 5000:
                    return DownloadResult(success=True, file_path=path, track_info=track_info)
            await asyncio.sleep(1)
        return DownloadResult(success=False, error_message="File not found after download", track_info=track_info)

    async def _convert_to_mp3(self, input_path: Path, track_info: TrackInfo) -> DownloadResult:
        if not input_path.exists(): return DownloadResult(success=False, error_message="Input file not found", track_info=track_info)
        output_path = input_path.with_suffix(".mp3")
        if input_path.suffix.lower() == '.mp3': return DownloadResult(success=True, file_path=input_path, track_info=track_info)
        try:
            cmd = ['ffmpeg', '-i', str(input_path), '-y', '-codec:a', 'libmp3lame', '-q:a', '4', str(output_path)]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 5000:
                try: input_path.unlink()
                except: pass
                return DownloadResult(success=True, file_path=output_path, track_info=track_info)
        except Exception as e: logger.error(f"FFmpeg conversion failed: {e}")
        return DownloadResult(success=True, file_path=input_path, track_info=track_info)