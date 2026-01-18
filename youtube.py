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
    ADAPTER: RAILWAY 'CERBERUS' EDITION (2026)
    - Multi-layered download strategy: Piped -> yt-dlp -> yt-music
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
                with open(self.cookies_path, "w", encoding="utf-8") as f: f.write(cookies_content)
                logger.info("🍪 Cookies loaded.")
            except Exception as e:
                logger.error(f"Failed to write cookies: {e}")

        self.semaphore = asyncio.Semaphore(1) 
        self.search_semaphore = asyncio.Semaphore(2)

        self.search_opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "socket_timeout": 20, "retries": 3}
        if self.cookies_path.exists():
            self.search_opts['cookiefile'] = str(self.cookies_path)
        
        self.ytdlp_fallback_opts = {
            "quiet": True, "no_warnings": True,
            "format": "bestaudio[asr=44100]/bestaudio/best",
            "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "postprocessors": [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
            "keepvideo": False, "socket_timeout": 30, "retries": 10, "ignoreerrors": True, 'nocheckcertificate': True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"], "player_skip": ["webpage"]}},
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.5",
            },
        }
        if self.cookies_path.exists(): self.ytdlp_fallback_opts['cookiefile'] = str(self.cookies_path)

        logger.info("🟢 YouTube 'Cerberus' Engine initialized.")

    async def search(self, query: str, search_mode: str = 'genre', decade: Optional[str] = None, limit: int = 20) -> List[TrackInfo]:
        # This method is stable and does not need changes
        clean_query = query.lower().strip(); cache_key = f"yt_search_cerberus:{clean_query}"
        cached = await self._cache.get(cache_key)
        if cached: return cached
        async with self.search_semaphore:
            loop = asyncio.get_running_loop()
            def do_search():
                with yt_dlp.YoutubeDL(self.search_opts) as ydl:
                    try: return ydl.extract_info(f"ytsearch{limit}:{clean_query} audio", download=False)
                    except Exception: return None
            res = await loop.run_in_executor(None, do_search)
            results = [TrackInfo(identifier=str(e.get('id','')), title=e.get('title',''), artist=e.get('channel',''), duration=int(e.get('duration') or 0), source=Source.YOUTUBE) for e in res.get('entries',[]) if e] if res else []
            if results: await self._cache.set(cache_key, results, ttl=3600)
            return results

    async def download(self, video_id: str, track_info: Optional[TrackInfo] = None) -> DownloadResult:
        if not track_info:
            track_info = TrackInfo(identifier=video_id, title="Unknown Track", artist="Web Player", duration=0, source=Source.YOUTUBE)

        if not video_id or video_id.startswith('--') or len(video_id) < 8:
            return DownloadResult(success=False, error_message="Invalid video ID", track_info=track_info)

        cached_file_id = await self._cache.get(f"file_id:{video_id}")
        if cached_file_id: return DownloadResult(success=True, file_id=cached_file_id, track_info=track_info)
        
        final_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
        if final_path.exists() and final_path.stat().st_size > 10000:
            return DownloadResult(success=True, file_path=final_path, track_info=track_info)
        
        # --- Multi-layered download strategy ---
        result = await self._download_piped(video_id, track_info)
        if not result.success: result = await self._download_ytdlp_minimal(video_id, track_info)
        if not result.success: result = await self._download_direct_ytmusic(video_id, track_info)
        
        if result.success and result.file_path and result.file_path.suffix != ".mp3":
            result = await self._run_ffmpeg_postprocessor(result.file_path, track_info)

        if result.success:
             return DownloadResult(success=True, file_path=result.file_path, track_info=track_info)
        return result

    async def _download_piped(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        # Implementation from user's source, adapted
        piped_instances = self._settings.PIPED_INSTANCE_LIST; random.shuffle(piped_instances)
        async with httpx.AsyncClient(timeout=20.0, limits=httpx.Limits(max_connections=5), follow_redirects=True) as client:
            for instance in piped_instances:
                try:
                    info_url = f"{instance}/streams/{video_id}"; info_resp = await client.get(info_url); info_resp.raise_for_status(); data = info_resp.json()
                    if data.get("error"): continue
                    audio_streams = data.get("audioStreams", []); audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                    if not audio_streams: continue
                    for stream in audio_streams:
                        try:
                            audio_url = stream.get("url"); file_ext = stream.get("format", "webm").lower(); file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.{file_ext}"
                            if not audio_url: continue
                            async with client.stream("GET", audio_url, timeout=60) as response:
                                response.raise_for_status()
                                with file_path.open("wb") as f:
                                    async for chunk in response.aiter_bytes(): f.write(chunk)
                            if file_path.exists() and file_path.stat().st_size > 10000:
                                return DownloadResult(success=True, file_path=file_path, track_info=track_info)
                        except Exception: continue
                except Exception: continue
        return DownloadResult(success=False, error_message="All Piped instances failed")
        
    async def _download_ytdlp_minimal(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        # This is the "ytdlp_fallback_opts" method
        return await self._execute_ytdlp_download(video_id, track_info, self.ytdlp_fallback_opts)

    async def _download_direct_ytmusic(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        # This is the "direct YouTube Music" method
        opts = {
            "quiet": True, "no_warnings": True, "format": "bestaudio", "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            "postprocessors": [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            "keepvideo": False, "socket_timeout": 30, "retries": 5, "ignoreerrors": True, 'nocheckcertificate': True,
            "extractor_args": {"youtube": {"player_client": ["android_music"]}},
            "http_headers": {"User-Agent": "com.google.android.apps.youtube.music/6.21.51", "X-YouTube-Client-Name": "67"},
            "cookiefile": str(self.cookies_path) if self.cookies_path.exists() else None,
        }
        return await self._execute_ytdlp_download(video_id, track_info, opts, f"https://music.youtube.com/watch?v={video_id}")

    async def _execute_ytdlp_download(self, video_id: str, track_info: Optional[TrackInfo], opts: dict, url: Optional[str] = None) -> DownloadResult:
        url = url or f"https://www.youtube.com/watch?v={video_id}"
        async with self.semaphore:
            loop = asyncio.get_running_loop()
            def do_download():
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
                    return True
                except Exception as e:
                    logger.error(f"yt-dlp execution error for '{video_id}': {e}", exc_info=True)
                    return False
            try:
                success = await asyncio.wait_for(loop.run_in_executor(None, do_download), timeout=90.0)
                if success: return await self._wait_for_file(video_id, track_info)
            except asyncio.TimeoutError:
                logger.error(f"yt-dlp execution timeout for {video_id}")
        return DownloadResult(success=False, error_message="yt-dlp execution failed")

    async def _run_ffmpeg_postprocessor(self, input_path: Path, track_info: Optional[TrackInfo]) -> DownloadResult:
        output_path = input_path.with_suffix(".mp3")
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', str(input_path), '-y', '-codec:a', 'libmp3lame', '-q:a', '2', str(output_path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            if proc.returncode == 0:
                try: input_path.unlink()
                except OSError: pass
                return DownloadResult(success=True, file_path=output_path, track_info=track_info)
        except Exception: pass
        return DownloadResult(success=False, error_message="FFmpeg conversion failed", track_info=track_info)

    async def _wait_for_file(self, video_id: str, track_info: Optional[TrackInfo]) -> DownloadResult:
        start_wait = time.time()
        while time.time() - start_wait < 15:
            path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if path.exists() and path.stat().st_size > 10000:
                return DownloadResult(success=True, file_path=path, track_info=track_info)
            await asyncio.sleep(1)
        return DownloadResult(success=False, error_message="File not found after download", track_info=track_info)