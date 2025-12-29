import asyncio
import logging
import random
import os
from typing import List, Optional, Dict, Set
from dataclasses import dataclass, field

from telegram import Bot, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest

from config import Settings, MUSIC_CATALOG
from models import TrackInfo, DownloadResult
from youtube import YouTubeDownloader

logger = logging.getLogger("radio")

def format_duration(seconds: int) -> str:
    mins, secs = divmod(seconds, 60)
    return f"{mins}:{secs:02d}"

def get_now_playing_message(track: TrackInfo, genre_name: str, decade: Optional[str] = None) -> str:
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
    tracks_played: int = field(init=False, default=0)
    consecutive_errors: int = field(init=False, default=0)
    
    async def start(self):
        if self.is_running: return
        self.is_running = True
        self.current_task = asyncio.create_task(self._radio_loop())
        logger.info(f"[{self.chat_id}] 🚀 Radio started: '{self.query}'")

    async def stop(self):
        self.is_running = False
        if self.current_task: self.current_task.cancel()
        await self._delete_status()
        logger.info(f"[{self.chat_id}] 🛑 Radio stopped.")

    async def skip(self):
        self.skip_event.set()

    async def _update_status(self, text: str):
        try:
            if self.status_message:
                await self.status_message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
            else:
                self.status_message = await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.MARKDOWN)
        except Exception: 
            self.status_message = None # Если сообщение удалено юзером, создадим новое при следующем треке

    async def _delete_status(self):
        if self.status_message:
            try: await self.status_message.delete()
            except Exception: pass
            self.status_message = None

    async def _fill_playlist(self, retry_query: str = None):
        target_query = retry_query or self.query
        await self._update_status(f"📡 Сканирование эфира: *{self.display_name}*...")
        
        try:
            # Ищем чуть больше треков
            tracks = await self.downloader.search(target_query, decade=self.decade, limit=25)
            # Исключаем уже прослушанные
            new_tracks = [t for t in tracks if t.identifier not in self.played_ids]
            
            if new_tracks:
                random.shuffle(new_tracks)
                self.playlist.extend(new_tracks)
                logger.info(f"[{self.chat_id}] +{len(new_tracks)} tracks found.")
            else:
                logger.warning(f"[{self.chat_id}] Empty search for '{target_query}'.")
        except Exception as e:
            logger.error(f"[{self.chat_id}] Search error: {e}")

    async def _activate_emergency_protocol(self):
        """Если совсем всё плохо - включаем мировые хиты."""
        fallbacks = [
            ("Global Top 50", "top 50 global hits"),
            ("Summer Hits", "summer hits 2024"),
            ("Lo-Fi Chill", "lofi hip hop radio")
        ]
        name, query = random.choice(fallbacks)
        logger.info(f"[{self.chat_id}] 🆘 Emergency protocol: {name}")
        await self._update_status(f"⚠️ Сигнал потерян. Переключение на резервную частоту: *{name}*")
        await self._fill_playlist(retry_query=query)

    async def _radio_loop(self):
        while self.is_running:
            try:
                # 1. Если плейлист пуст -> пополняем
                if len(self.playlist) < 3:
                    await self._fill_playlist()
                
                # 2. Если всё еще пуст -> Аварийный протокол (не выключаемся!)
                if not self.playlist:
                    await self._activate_emergency_protocol()
                    if not self.playlist:
                        # Если даже аварийный пуст, ждем 10 сек и пробуем снова (Loop Protection)
                        await asyncio.sleep(10)
                        continue

                # 3. Берем трек
                track = self.playlist.pop(0)
                self.played_ids.add(track.identifier)
                # Чистим историю, чтобы не переполнять память
                if len(self.played_ids) > 300: 
                    self.played_ids = set(list(self.played_ids)[150:])

                # 4. Играем
                success = await self._play_track(track)
                
                if success:
                    self.consecutive_errors = 0
                    self.tracks_played += 1
                    # Ждем пока трек доиграет или будет скипнут
                    # Тайм-аут чуть меньше длительности трека, чтобы начать грузить следующий заранее? 
                    # Нет, тут просто ждем ивента.
                    try:
                        # Ждем событие skip или просто паузу между треками (эмуляция прослушивания)
                        # В реальности мы не знаем когда трек кончился в Telegram, 
                        # поэтому просто ждем ~80% длительности трека или 3 минуты макс
                        wait_time = min(track.duration, 180) 
                        await asyncio.wait_for(self.skip_event.wait(), timeout=wait_time)
                    except asyncio.TimeoutError:
                        pass # Трек доиграл (условно)
                else:
                    self.consecutive_errors += 1
                    logger.warning(f"[{self.chat_id}] Error playing track. Streak: {self.consecutive_errors}")
                    await asyncio.sleep(2) # Пауза перед следующей попыткой
                    
                self.skip_event.clear()

            except asyncio.CancelledError:
                break # Единственный валидный выход из цикла
            except Exception as e:
                logger.error(f"[{self.chat_id}] Loop crash: {e}", exc_info=True)
                await asyncio.sleep(5) # Защита от спама ошибками

        self.is_running = False

    async def _play_track(self, track: TrackInfo) -> bool:
        try:
            await self._update_status(f"⬇️ Загрузка: *{track.title}*...")
            
            # Скачиваем с повторными попытками внутри downloader
            result = await self.downloader.download(track.identifier)
            
            if not result or not result.success: 
                return False
            
            caption = get_now_playing_message(track, self.display_name, self.decade)
            markup = None
            base_url = self.settings.BASE_URL.strip() if self.settings.BASE_URL else ""

            if base_url.startswith("https") and self.chat_type != ChatType.CHANNEL:
                if self.chat_type == ChatType.PRIVATE:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=base_url))]])
                else:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть плеер", url=base_url)]])

            # Отправка
            if result.file_id:
                await self.bot.send_audio(self.chat_id, audio=result.file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            elif result.file_path:
                with open(result.file_path, 'rb') as f:
                    msg = await self.bot.send_audio(self.chat_id, audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                    if msg.audio: await self.downloader.cache_file_id(track.identifier, msg.audio.file_id)
            
            # Удаляем статус "загрузка", оставляем трек
            await self._delete_status()
            return True

        except Exception as e:
            logger.error(f"Play track error: {e}")
            return False
        finally:
            # Чистим файл
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
            # Если уже играет, стопаем старое
            if chat_id in self._sessions and self._sessions[chat_id].is_running:
                await self._sessions[chat_id].stop()
            
            if query == "random":
                query, decade, display_name = self._get_random_query()

            session = RadioSession(
                chat_id=chat_id, bot=self._bot, downloader=self._downloader, settings=self._settings,
                query=query, display_name=(display_name or query), decade=decade, chat_type=chat_type
            )
            self._sessions[chat_id] = session
            await session.start()

    async def stop(self, chat_id: int):
        async with self._get_lock(chat_id):
            if session := self._sessions.pop(chat_id, None):
                await session.stop()

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            await session.skip()

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()):
            await self.stop(chat_id)

    def _get_random_query(self) -> tuple[str, Optional[str], str]:
        try:
            all_queries = []
            def _flatten_queries(catalog_level: dict):
                for name, value in catalog_level.items():
                    if isinstance(value, dict): _flatten_queries(value)
                    elif isinstance(value, str): all_queries.append((name, value))

            _flatten_queries(MUSIC_CATALOG)
            if not all_queries: return ("top hits", None, "Top Hits")
            display_name, query = random.choice(all_queries)
            return (query, None, display_name)
        except Exception:
            return ("pop music", None, "Pop Music")
