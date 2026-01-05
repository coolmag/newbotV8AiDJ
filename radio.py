import asyncio
import logging
import random
import os
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
        """Обработка блокировки бота пользователем."""
        logger.error(f"[{self.chat_id}] ⛔️ Бот заблокирован пользователем. Аварийная остановка сессии.")
        self.is_running = False
        self.skip_event.set() # Разблокируем ожидание, если оно есть

    async def _update_status(self, text: str):
        if not self.is_running: return
        try:
            if self.status_message:
                try:
                    await self.status_message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
                    return
                except BadRequest as e:
                    if "Message is not modified" in str(e): return
                    # Если сообщение старое или удалено, сбрасываем и шлем новое
                    self.status_message = None
            
            self.status_message = await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.MARKDOWN)
        
        except Forbidden:
            await self._handle_forbidden()
        except RetryAfter as e:
            logger.warning(f"[{self.chat_id}] Flood limit. Sleep {e.retry_after}")
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            logger.warning(f"[{self.chat_id}] Status error: {e}")
            self.status_message = None

    async def _delete_status(self):
        if self.status_message:
            try: await self.status_message.delete()
            except: pass
            self.status_message = None

    async def _fill_playlist(self, retry_query: str = None):
        if self._is_searching or not self.is_running: return
        self._is_searching = True
        target_query = retry_query or self.query
        
        # Не спамим статусом, если это повторная попытка
        if not retry_query:
            await self._update_status(f"📡 Сканирование эфира: *{self.display_name}*...")
            
        try:
            tracks = await self.downloader.search(target_query, decade=self.decade, limit=25)
            if not self.is_running: return # Проверка на случай если заблочили во время поиска

            new_tracks = [t for t in tracks if t.identifier not in self.played_ids]
            if new_tracks:
                random.shuffle(new_tracks)
                self.playlist.extend(new_tracks)
                logger.info(f"[{self.chat_id}] Добавлено треков: {len(new_tracks)} (Query: {target_query})")
            else:
                logger.warning(f"[{self.chat_id}] Поиск '{target_query}' вернул 0 новых треков.")
        except Exception as e:
            logger.error(f"Search error: {e}")
        finally:
            self._is_searching = False

    async def _radio_loop(self):
        consecutive_errors = 0
        while self.is_running:
            try:
                # 1. Пополнение плейлиста
                if len(self.playlist) < 3: 
                    await self._fill_playlist()
                
                # 2. Обработка пустого плейлиста (Fallback)
                if not self.playlist:
                    logger.info(f"[{self.chat_id}] Плейлист пуст. Пробую резервные частоты...")
                    await self._update_status("⚠️ Сигнал слаб. Ищу резервную волну...")
                    
                    # Разные фолбэки в зависимости от оригинального запроса
                    fallbacks = ["global top 50 hits", "lofi hip hop radio", "80s greatest hits", "viral pop hits"]
                    if "rock" in self.query.lower(): fallbacks = ["classic rock hits", "modern rock radio"]
                    
                    await self._fill_playlist(retry_query=random.choice(fallbacks))
                    
                    if not self.playlist:
                        consecutive_errors += 1
                        if consecutive_errors > 5:
                            logger.error(f"[{self.chat_id}] 💀 Не удалось найти треки после 5 попыток. Остановка.")
                            await self.stop()
                            break
                        await asyncio.sleep(10)
                        continue

                # 3. Воспроизведение
                track = self.playlist.pop(0)
                self.played_ids.add(track.identifier)
                # Ограничиваем историю, чтобы память не текла
                if len(self.played_ids) > 200: 
                    self.played_ids = set(list(self.played_ids)[100:])

                success = await self._play_track(track)
                
                if success:
                    consecutive_errors = 0
                    # Ждем конца трека или пропуска
                    wait_time = min(track.duration, 300) if track.duration > 0 else 180
                    try: 
                        await asyncio.wait_for(self.skip_event.wait(), timeout=wait_time)
                    except asyncio.TimeoutError: 
                        pass 
                else:
                    consecutive_errors += 1
                    # Экспоненциальная задержка при ошибках, но не более 60 сек
                    wait_backoff = min(5 * consecutive_errors, 60)
                    await asyncio.sleep(wait_backoff)
                
                self.skip_event.clear()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Critical loop error: {e}")
                await asyncio.sleep(10)
        
        self.is_running = False

    async def _play_track(self, track: TrackInfo) -> bool:
        if not self.is_running: return False
        try:
            await self._update_status(f"⬇️ Загрузка: *{track.title}*...")
            # Проверяем is_running снова после await
            if not self.is_running: return False

            result = await self.downloader.download(track.identifier)
            if not result or not result.success: 
                logger.warning(f"[{self.chat_id}] Ошибка загрузки {track.identifier}: {result.error_message if result else 'Unknown'}")
                return False
            
            caption = get_now_playing_message(track, self.display_name)
            markup = None
            base_url = self.settings.BASE_URL.strip() if self.settings.BASE_URL else ""
            if base_url.startswith("https") and self.chat_type != ChatType.CHANNEL:
                if self.chat_type == ChatType.PRIVATE:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=base_url))]])
                else:
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть плеер", url=base_url)]])

            try:
                if result.file_id:
                    await self.bot.send_audio(self.chat_id, audio=result.file_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                elif result.file_path:
                    with open(result.file_path, 'rb') as f:
                        msg = await self.bot.send_audio(self.chat_id, audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
                        if msg.audio: await self.downloader.cache_file_id(track.identifier, msg.audio.file_id)
            except Forbidden:
                await self._handle_forbidden()
                return False
            except Exception as e:
                logger.error(f"Send audio error: {e}")
                return False
            
            await self._delete_status()
            return True
        except Exception as e:
            logger.error(f"Play wrapper error: {e}")
            return False
        finally:
            # Очистка файла (если он не закэширован как file_id, удаляем локально для экономии места, если нужно)
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
            if chat_id in self._sessions: 
                # Если сессия уже есть, просто скипаем трек или меняем запрос?
                # Для простоты - перезапускаем
                await self._sessions[chat_id].stop()
            
            if query == "random": 
                query, decade, display_name = self._get_random_query()
            
            session = RadioSession(
                chat_id=chat_id, 
                bot=self._bot, 
                downloader=self._downloader, 
                settings=self._settings, 
                query=query, 
                display_name=(display_name or query), 
                decade=decade, 
                chat_type=chat_type
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
        tasks = [self.stop(cid) for cid in list(self._sessions.keys())]
        if tasks: await asyncio.gather(*tasks)

    def _get_random_query(self) -> tuple[str, Optional[str], str]:
        all_queries = []
        def _flatten(cat):
            for k, v in cat.items():
                if isinstance(v, dict): _flatten(v)
                else: 
                    # v can be a string (query) or dict
                    pass 
                # Исправленная логика обхода (структура сложная)
                # В текущем catalog.py: ключи -> вложенные dict -> в конце строка (query)
        
        # Упрощенный сбор всех query из MUSIC_CATALOG
        def extract_queries(node, path=""):
            for key, val in node.items():
                if isinstance(val, dict):
                    if "query" in val: # Это конечный узел
                        all_queries.append((val["query"], None, val["name"]))
                    elif "children" in val: # Это структура меню
                        extract_queries(val["children"])
                    else: # Просто вложенность (как в старом формате)
                        extract_queries(val)
                elif isinstance(val, str) and key != "name" and key != "action":
                     # Старый формат каталога
                     all_queries.append((val, None, key))

        extract_queries(MUSIC_CATALOG)
        if not all_queries: return ("top 50 global hits", None, "Random")
        return random.choice(all_queries)