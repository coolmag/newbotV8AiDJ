import asyncio
import logging
import random
import os
import traceback
from typing import List, Optional, Dict, Set
from dataclasses import dataclass, field

from telegram import Bot, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest, RetryAfter, Forbidden

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

    async def _handle_forbidden(self):
        logger.error(f"[{self.chat_id}] ⛔️ Бот заблокирован. Стоп.")
        self.is_running = False
        self.skip_event.set()

    async def _update_status(self, text: str):
        if not self.is_running: return
        try:
            if self.status_message:
                try:
                    await self.status_message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
                    return
                except BadRequest: self.status_message = None
            
            self.status_message = await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.MARKDOWN)
        except Forbidden: await self._handle_forbidden()
        except Exception: self.status_message = None

    async def _delete_status(self):
        if self.status_message:
            try: await self.status_message.delete()
            except: pass
            self.status_message = None

    async def _fill_playlist(self, retry_query: str = None):
        if self._is_searching or not self.is_running: return
        self._is_searching = True
        logger.info(f"[{self.chat_id}] [DEBUG LOOP] _fill_playlist started")
        
        base_query = retry_query or self.query
        variations = [base_query, f"{base_query} mix", f"{base_query} hits"]
        if len(self.played_ids) > 10: random.shuffle(variations)

        found_new = False
        
        for q in variations:
            if not self.is_running: break
            try:
                logger.info(f"[{self.chat_id}] [DEBUG LOOP] searching for '{q}'")
                tracks = await self.downloader.search(q, decade=self.decade, limit=30)
                if not tracks: continue

                new_tracks = [t for t in tracks if t.identifier not in self.played_ids]
                if new_tracks:
                    random.shuffle(new_tracks)
                    self.playlist.extend(new_tracks)
                    logger.info(f"[{self.chat_id}] [DEBUG LOOP] Found {len(new_tracks)} new tracks.")
                    found_new = True
                    break
            except Exception as e:
                logger.error(f"Search error for {q}: {e}")
        
        if not found_new:
            logger.warning(f"[{self.chat_id}] [DEBUG LOOP] No new tracks found, trying cache fallback")
            if not self.playlist:
                cached = await self.downloader.get_random_cached_tracks(limit=10)
                if cached:
                    self.playlist.extend(cached)
                    logger.info(f"[{self.chat_id}] Added {len(cached)} cached tracks")
            
        self._is_searching = False
        logger.info(f"[{self.chat_id}] [DEBUG LOOP] _fill_playlist finished. Playlist size: {len(self.playlist)}")

    async def _radio_loop(self):
        logger.info(f"[{self.chat_id}] [DEBUG LOOP] Starting loop")
        consecutive_errors = 0
        while self.is_running:
            try:
                logger.info(f"[{self.chat_id}] [DEBUG LOOP] Iteration start. Queue: {len(self.playlist)}")
                
                # 1. Пополнение
                if len(self.playlist) < 3: 
                    logger.info(f"[{self.chat_id}] [DEBUG LOOP] Calling _fill_playlist")
                    await self._fill_playlist()
                    logger.info(f"[{self.chat_id}] [DEBUG LOOP] Returned from _fill_playlist")
                
                # 2. Если всё равно пусто
                if not self.playlist:
                    logger.warning(f"[{self.chat_id}] [DEBUG LOOP] Playlist empty after fill. Sleeping.")
                    await self._update_status("📡 Поиск сигнала...")
                    await asyncio.sleep(5)
                    continue

                # 3. Играем
                track = self.playlist.pop(0)
                self.played_ids.add(track.identifier)
                if len(self.played_ids) > 300: self.played_ids = set(list(self.played_ids)[150:])

                logger.info(f"[{self.chat_id}] [DEBUG LOOP] Attempting to play: {track.title} ({track.identifier})")
                success = await self._play_track(track)
                logger.info(f"[{self.chat_id}] [DEBUG LOOP] Play result: {success}")
                
                if success:
                    consecutive_errors = 0
                    wait_time = min(track.duration, 300) if track.duration > 0 else 180
                    try: 
                        logger.info(f"[{self.chat_id}] [DEBUG LOOP] Waiting for end of track ({wait_time}s)")
                        await asyncio.wait_for(self.skip_event.wait(), timeout=wait_time)
                    except asyncio.TimeoutError: pass 
                else:
                    consecutive_errors += 1
                    logger.error(f"[{self.chat_id}] [DEBUG LOOP] Play failed (error count: {consecutive_errors})")
                    await asyncio.sleep(2)
                
                self.skip_event.clear()
                
            except asyncio.CancelledError: 
                logger.info(f"[{self.chat_id}] [DEBUG LOOP] Cancelled")
                break
            except Exception as e:
                logger.error(f"[{self.chat_id}] [DEBUG LOOP] CRASH: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)
        
        self.is_running = False
        logger.info(f"[{self.chat_id}] [DEBUG LOOP] Loop finished")

    async def _play_track(self, track: TrackInfo) -> bool:
        if not self.is_running: return False
        try:
            await self._update_status(f"⬇️ Загрузка: *{track.title}*...")
            
            logger.info(f"[{self.chat_id}] [DEBUG PLAY] Calling downloader.download for {track.identifier}")
            result = await self.downloader.download(track.identifier, track_info=track)
            
            if not result or not result.success:
                logger.warning(f"[{self.chat_id}] [DEBUG PLAY] Download failed: {result.error_message if result else 'None'}")
                return False
            
            logger.info(f"[{self.chat_id}] [DEBUG PLAY] Download success. File: {result.file_path}, ID: {result.file_id}")

            caption = get_now_playing_message(track, self.display_name)
            markup = None
            base_url = self.settings.BASE_URL.strip() if self.settings.BASE_URL else ""
            if base_url.startswith("https") and self.chat_type != ChatType.CHANNEL:
                if self.chat_type == ChatType.PRIVATE:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Плеер", web_app=WebAppInfo(url=base_url))]])
                else:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Плеер", url=base_url)]])

            try:
                if result.file_id:
                    logger.info(f"[{self.chat_id}] [DEBUG PLAY] Sending by ID...")
                    await self.bot.send_audio(self.chat_id, audio=result.file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                elif result.file_path:
                    logger.info(f"[{self.chat_id}] [DEBUG PLAY] Sending by File...")
                    with open(result.file_path, 'rb') as f:
                        msg = await self.bot.send_audio(self.chat_id, audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                        if msg.audio: await self.downloader.cache_file_id(track.identifier, msg.audio.file_id)
            except Forbidden:
                await self._handle_forbidden()
                return False
            except Exception as e:
                logger.warning(f"[{self.chat_id}] [DEBUG PLAY] Send failed: {e}. Invalidating cache.")
                if result.file_id:
                    await self.downloader.invalidate_cache(track.identifier)
                    await self._update_status(f"🔄 Перекачиваю: *{track.title}*...")
                    result = await self.downloader.download(track.identifier, track_info=track)
                    if result.success and result.file_path:
                         with open(result.file_path, 'rb') as f:
                             msg = await self.bot.send_audio(self.chat_id, audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                             if msg.audio: await self.downloader.cache_file_id(track.identifier, msg.audio.file_id)
                         return True
                return False
            
            await self._delete_status()
            return True
        except Exception as e:
            logger.error(f"[{self.chat_id}] [DEBUG PLAY] Critical error: {e}")
            traceback.print_exc()
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
            
            session = RadioSession(
                chat_id=chat_id, bot=self._bot, downloader=self._downloader, 
                settings=self._settings, query=query, display_name=(display_name or query), 
                decade=decade, chat_type=chat_type
            )
            self._sessions[chat_id] = session
            await session.start()

    async def stop(self, chat_id: int):
        async with self._get_lock(chat_id):
            if session := self._sessions.pop(chat_id, None): await session.stop()

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id): await session.skip()

    async def stop_all(self):
        tasks = [self.stop(cid) for cid in list(self._sessions.keys())]
        if tasks: await asyncio.gather(*tasks)

    def _get_random_query(self) -> tuple[str, Optional[str], str]:
        all_queries = []
        def extract(node):
            for k, v in node.items():
                if isinstance(v, dict):
                    if "query" in v: all_queries.append((v["query"], None, v.get("name", k)))
                    elif "children" in v: extract(v["children"])
                    else: extract(v)
        extract(MUSIC_CATALOG)
        return random.choice(all_queries) if all_queries else ("top hits", None, "Random")