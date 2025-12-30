import asyncio
import logging
import random
import os
from typing import List, Optional, Dict, Set
from dataclasses import dataclass, field

from telegram import Bot, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest, RetryAfter

from config import Settings
from models import TrackInfo, DownloadResult
from youtube import YouTubeDownloader

import json
from pathlib import Path

# Load MUSIC_CATALOG from genres.json
with open(Path(__file__).parent / "genres.json", "r", encoding="utf-8") as f:
    MUSIC_CATALOG = json.load(f)

logger = logging.getLogger("radio")

def format_duration(seconds: int) -> str:
    mins, secs = divmod(seconds, 60)
    return f"{mins}:{secs:02d}"

def get_now_playing_message(track: TrackInfo, genre_name: str) -> str:
    icon = random.choice(["🎧", "🎵", "🎶", "📻", "💿"])
    title = track.title[:40].strip()
    artist = track.artist[:30].strip()
    return f"{icon} *{title}*\n👤 {artist}\n⏱ {format_duration(track.duration)} | 📻 _{genre_name}_"

@dataclass
class RadioSession:
    chat_id: int
    bot: Bot
    downloader: YouTubeDownloader
    settings: Settings
    query: str
    display_name: str
    chat_type: Optional[str] = None
    decade: Optional[str] = None
    
    is_running: bool = field(init=False, default=False)
    playlist: List[TrackInfo] = field(default_factory=list)
    played_ids: Set[str] = field(default_factory=set)
    current_task: Optional[asyncio.Task] = None
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    status_message: Optional[Message] = None
    _is_searching: bool = field(init=False, default=False)
    
    async def start(self):
        if self.is_running: return
        self.is_running = True
        self.current_task = asyncio.create_task(self._radio_loop())
        logger.info(f"[{self.chat_id}] 🚀 Эфир запущен: '{self.query}'")

    async def stop(self):
        self.is_running = False
        if self.current_task: self.current_task.cancel()
        await self._delete_status()
        logger.info(f"[{self.chat_id}] 🛑 Эфир остановлен.")

    async def skip(self):
        self.skip_event.set()

    async def _update_status(self, text: str):
        try:
            if self.status_message:
                try:
                    await self.status_message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
                    return
                except BadRequest as e:
                    if "Message is not modified" in str(e): return
                    self.status_message = None
            self.status_message = await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.MARKDOWN)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            logger.warning(f"Status error: {e}")
            self.status_message = None

    async def _delete_status(self):
        if self.status_message:
            try: await self.status_message.delete()
            except: pass
            self.status_message = None

    async def _fill_playlist(self, retry_query: str = None):
        if self._is_searching: return
        self._is_searching = True
        target_query = retry_query or self.query
        await self._update_status(f"📡 Сканирование эфира: *{self.display_name}*...")
        try:
            tracks = await self.downloader.search(target_query, decade=self.decade, limit=25)
            new_tracks = [t for t in tracks if t.identifier not in self.played_ids]
            if new_tracks:
                random.shuffle(new_tracks)
                self.playlist.extend(new_tracks)
                logger.info(f"[{self.chat_id}] Найдено треков: {len(new_tracks)}")
            else:
                logger.warning(f"[{self.chat_id}] Поиск '{target_query}' пуст.")
        except Exception as e:
            logger.error(f"Search error: {e}")
        finally:
            self._is_searching = False

    async def _radio_loop(self):
        consecutive_errors = 0
        while self.is_running:
            try:
                if len(self.playlist) < 3: await self._fill_playlist()
                
                if not self.playlist:
                    await self._update_status("⚠️ Сигнал слаб. Ищу резервную волну...")
                    fallbacks = ["top 50 hits", "lofi radio", "80s music"]
                    await self._fill_playlist(retry_query=random.choice(fallbacks))
                    if not self.playlist:
                        await asyncio.sleep(10)
                        continue

                track = self.playlist.pop(0)
                self.played_ids.add(track.identifier)
                if len(self.played_ids) > 200: self.played_ids = set(list(self.played_ids)[100:])

                success = await self._play_track(track)
                if success:
                    consecutive_errors = 0
                    wait_time = min(track.duration, 240) if track.duration > 0 else 180
                    try: await asyncio.wait_for(self.skip_event.wait(), timeout=wait_time)
                    except asyncio.TimeoutError: pass 
                else:
                    consecutive_errors += 1
                    wait_backoff = min(5 * consecutive_errors, 30)
                    await asyncio.sleep(wait_backoff)
                self.skip_event.clear()
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"Critical loop error: {e}")
                await asyncio.sleep(10)
        self.is_running = False

    async def _play_track(self, track: TrackInfo) -> bool:
        try:
            await self._update_status(f"⬇️ Загрузка: *{track.title}*...")
            result = await self.downloader.download(track.identifier)
            if not result or not result.success: return False
            
            caption = get_now_playing_message(track, self.display_name)
            markup = None
            base_url = self.settings.BASE_URL.strip() if self.settings.BASE_URL else ""
            if base_url.startswith("https") and self.chat_type != ChatType.CHANNEL:
                if self.chat_type == ChatType.PRIVATE:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=base_url))]])
                else:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть плеер", url=base_url)]])

            if result.file_id:
                await self.bot.send_audio(self.chat_id, audio=result.file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            elif result.file_path:
                with open(result.file_path, 'rb') as f:
                    msg = await self.bot.send_audio(self.chat_id, audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                    if msg.audio: await self.downloader.cache_file_id(track.identifier, msg.audio.file_id)
            
            await self._delete_status()
            return True
        except Exception as e:
            logger.error(f"Play error: {e}")
            return False
        finally:
            if result and result.file_path and os.path.exists(result.file_path):
                try: os.unlink(result.file_path)
                except: pass

class RadioManager:
    def __init__(self, bot: Bot, settings: Settings, downloader: YouTubeDownloader):
        self._bot, self._settings, self._downloader = bot, settings, downloader
        self._sessions: Dict[int, RadioSession] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, chat_id: int) -> asyncio.Lock:
        self._locks.setdefault(chat_id, asyncio.Lock())
        return self._locks[chat_id]

    async def start(self, chat_id: int, query: str, chat_type: Optional[str] = None, display_name: Optional[str] = None, decade: Optional[str] = None):
        async with self._get_lock(chat_id):
            if chat_id in self._sessions: await self._sessions[chat_id].stop()
            if query == "random": query, decade, display_name = self._get_random_query()
            session = RadioSession(chat_id=chat_id, bot=self._bot, downloader=self._downloader, settings=self._settings, query=query, display_name=(display_name or query), decade=decade, chat_type=chat_type)
            self._sessions[chat_id] = session
            await session.start()

    async def stop(self, chat_id: int):
        async with self._get_lock(chat_id):
            if session := self._sessions.pop(chat_id, None): await session.stop()

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id): await session.skip()

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()): await self.stop(chat_id)

    def _get_random_query(self) -> tuple[str, Optional[str], str]:
        all_queries = []
        def _flatten(cat):
            for k, v in cat.items():
                if isinstance(v, dict): _flatten(v)
                else: all_queries.append((k, v))
        _flatten(MUSIC_CATALOG)
        res = random.choice(all_queries)
        return (res[1], None, res[0])