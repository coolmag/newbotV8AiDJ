import asyncio
import logging
import random
import os
from typing import List, Optional, Dict, Set
from dataclasses import dataclass, field
from telegram import Bot, Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest

# Changed import
from config import Settings
from catalog import MUSIC_CATALOG 

from models import TrackInfo, DownloadResult
from youtube import YouTubeDownloader

logger = logging.getLogger("radio")

def format_duration(seconds: int) -> str:
    mins, secs = divmod(seconds, 60)
    return f"{mins}:{secs:02d}"

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
    tracks_played: int = field(init=False, default=0)
    
    async def start(self):
        if self.is_running: return
        self.is_running = True
        self.current_task = asyncio.create_task(self._radio_loop())
        logger.info(f"[{self.chat_id}] 🚀 Radio started: {self.query}")

    async def stop(self):
        self.is_running = False
        if self.current_task: self.current_task.cancel()
        await self._delete_status()

    async def skip(self):
        self.skip_event.set()

    async def _update_status(self, text: str):
        try:
            if self.status_message:
                await self.status_message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
            else:
                self.status_message = await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.MARKDOWN)
        except: self.status_message = None

    async def _delete_status(self):
        if self.status_message:
            try: await self.status_message.delete()
            except: pass
            self.status_message = None

    async def _fill_playlist(self):
        await self._update_status(f"🌌 Поиск: *{self.display_name}*")
        try:
            tracks = await self.downloader.search(self.query, decade=self.decade, limit=20)
            new_tracks = [t for t in tracks if t.identifier not in self.played_ids]
            random.shuffle(new_tracks)
            self.playlist.extend(new_tracks)
        except Exception as e: logger.error(f"Playlist error: {e}")

    async def _radio_loop(self):
        error_streak = 0
        while self.is_running:
            if len(self.playlist) < 3: await self._fill_playlist()
            if not self.playlist: break
            
            track = self.playlist.pop(0)
            self.played_ids.add(track.identifier)
            if len(self.played_ids) > 200: self.played_ids = set(list(self.played_ids)[100:])

            try:
                success = await self._play_track(track)
                if success:
                    error_streak = 0
                    # Ждем 90 сек или пропуска
                    try: await asyncio.wait_for(self.skip_event.wait(), timeout=90.0)
                    except asyncio.TimeoutError: pass
                else:
                    error_streak += 1
                    if error_streak >= 5: 
                        await self._update_status("❌ Ошибки воспроизведения. Стоп.")
                        break
            except Exception as e: logger.error(f"Loop error: {e}")
            finally: self.skip_event.clear()
        self.is_running = False

    async def _play_track(self, track: TrackInfo) -> bool:
        try:
            await self._update_status(f"🎶 Играет: *{track.title}*")
            res = await self.downloader.download(track.identifier)
            if not res.success: return False
            
            caption = f"🎧 *{track.title}*\n👤 {track.artist}\n📻 _{self.display_name}_"
            
            # --- БЕЗОПАСНАЯ КНОПКА (ОПЯТЬ) ---
            markup = None
            if self.chat_type == ChatType.PRIVATE and self.settings.BASE_URL:
                 markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Плеер", web_app=WebAppInfo(url=self.settings.BASE_URL))]])

            if res.file_id:
                await self.bot.send_audio(self.chat_id, res.file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            elif res.file_path:
                with open(res.file_path, 'rb') as f:
                    msg = await self.bot.send_audio(self.chat_id, f, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                    if msg.audio: await self.downloader.cache_file_id(track.identifier, msg.audio.file_id)
            
            # REMOVED: os.unlink(res.file_path) to prevent WebApp 404
            
            return True
        except Exception as e:
            logger.error(f"Play error: {e}")
            return False

class RadioManager:
    def __init__(self, bot, settings, downloader):
        self._bot, self._settings, self._downloader = bot, settings, downloader
        self._sessions = {}

    async def start(self, chat_id, query, chat_type=None):
        if chat_id in self._sessions: await self._sessions[chat_id].stop() 
        
        if query == "random":
            # Простой выбор рандома
            flat = []
            def r(d):
                for k,v in d.items():
                    if isinstance(v, dict): r(v)
                    else: flat.append((k,v))
            r(MUSIC_CATALOG)
            name, q = random.choice(flat)
        else:
            name, q = query, query

        s = RadioSession(chat_id, self._bot, self._downloader, self._settings, q, name, chat_type=chat_type)
        self._sessions[chat_id] = s
        await s.start()

    async def stop(self, chat_id):
        if s := self._sessions.pop(chat_id, None): await s.stop()

    async def skip(self, chat_id):
        if s := self._sessions.get(chat_id): await s.skip()

    async def stop_all(self):
        for cid in list(self._sessions.keys()): await self.stop(cid)