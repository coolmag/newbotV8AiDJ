import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
from typing import List
import os
import google.generativeai as genai
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import Application

from config import get_settings, Settings
from logging_setup import setup_logging
from radio import RadioManager
from youtube import YouTubeDownloader
from handlers import setup_handlers
from cache_service import CacheService
from models import TrackInfo

# Настройка (берет ключ из переменных окружения)
# Если ключа нет, код не упадет, но AI работать не будет
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime():
    return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения."""
    setup_logging()
    logger.info("⚡ Application starting up...")
    
    # 1. Загружаем настройки
    settings: Settings = get_settings()
    
    # 2. Создаём директории
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    settings.TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    
    # 3. Инициализируем кэш
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    # 4. Создаём загрузчик
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader # Store for API endpoints
    
    # 5. Создаём Telegram Application (с Bot'ом внутри)
    builder = Application.builder().token(settings.BOT_TOKEN)
    
    # Добавляем поддержку прокси, если он указан в настройках
    if settings.PROXY_URL:
        logger.info(f"Using proxy: {settings.PROXY_URL}")
        builder.proxy_url(settings.PROXY_URL)
        builder.get_updates_proxy_url(settings.PROXY_URL)
        
    tg_app = builder.build()
    
    # 6. Создаём RadioManager с Bot'ом из Application (ВАЖНО!)
    radio_manager = RadioManager(
        bot=tg_app.bot,  # Используем тот же Bot!
        settings=settings,
        downloader=downloader
    )
    
    # 7. Регистрируем хендлеры
    setup_handlers(
        app=tg_app,
        radio=radio_manager,
        settings=settings,
        downloader=downloader
    )
    
    # 8. Инициализируем и запускаем бота
    await tg_app.initialize()
    await tg_app.bot.set_my_commands([
        ("start", "🗂 Открыть меню жанров"),
        ("player", "🎧 Открыть веб-плеер"),
        ("play", "🔎 Поиск трека"),
        ("radio", "🎲 Случайное радио"),
        ("stop", "⏹️ Остановить"),
        ("skip", "⏭️ Пропустить трек")
    ])
    await tg_app.start()
    
    # 9. Устанавливаем вебхук
    webhook_url = settings.WEBHOOK_URL
    await tg_app.bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Bot started. Webhook: {webhook_url}")
    
    # Сохраняем в state
    app.state.tg_app = tg_app
    app.state.radio_manager = radio_manager
    app.state.cache = cache
    
    yield
    
    # --- Shutdown ---
    logger.info("🛑 Shutting down...")
    await radio_manager.stop_all()
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()
    logger.info("✅ Shutdown complete.")

app = FastAPI(lifespan=lifespan)

# --- CORS Middleware ---
# Разрешаем запросы от веб-плеера
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретный домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    """
    Отдаёт аудиофайл для воспроизведения в веб-плеере.
    """
    downloader: YouTubeDownloader = request.app.state.downloader
    
    # Сначала ищем готовый файл
    file_path = downloader._find_downloaded_file(video_id)
    
    if file_path and file_path.exists():
        return FileResponse(file_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")
    
    # Если файл не найден, инициируем загрузку и ждем ее завершения
    logger.info(f"Audio file not found for {video_id}, attempting to download and wait...")
    await downloader.download(video_id) # Инициируем, но не ждем здесь
    
    # Теперь ждем завершения
    final_path = await downloader.wait_for_download_completion(video_id)
    
    if final_path:
         return FileResponse(final_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")

    logger.error(f"Failed to download or find file for {video_id} after waiting.")
    return JSONResponse(status_code=404, content={"message": "Audio file not found"})


@app.get("/api/health")
async def health():
    return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist", response_model=dict)
async def get_playlist(query: str, request: Request):
    """
    Возвращает плейлист по заданному запросу.
    Используется веб-плеером.
    """
    downloader: YouTubeDownloader = request.app.state.downloader
    logger.info(f"API: Поиск плейлиста по запросу: '{query}'")
    try:
        # Ищем ~15 треков для плейлиста в веб-плеере
        tracks: List[TrackInfo] = await downloader.search(query=query, search_mode='track', limit=15)
        # FastAPI автоматически преобразует dataclass в JSON
        return {"playlist": tracks}
    except Exception as e:
        logger.error(f"API: Ошибка при поиске плейлиста: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error"})

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str):
    if not GEMINI_KEY:
        return {"error": "AI Brain not connected (No Key)"}

    print(f"[AI] Получен запрос: {prompt}")

    # Системный промпт для настройки личности
    system_instruction = """
    Ты — DJ Aurora, дерзкий и энергичный ведущий футуристического радио.
    Твоя задача:
    1. Подобрать 5 идеальных треков под запрос пользователя.
    2. Написать ОДНУ короткую, яркую фразу (интро), чтобы представить этот микс.
    3. Использовать молодежный сленг, но без грубости.
    
    Верни ответ ТОЛЬКО в формате JSON (без markdown):
    {
        "intro": "Текст, который ты скажешь голосом...",
        "tracks": ["Artist - Title", "Artist - Title", ...]
    }
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(f"{system_instruction}\n\nЗапрос пользователя: {prompt}")
        
        # Очистка от возможных markdown кавычек ```json ... ```
        clean_text = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(clean_text)
        
        # Теперь превращаем список названий в реальные объекты для плеера
        # (Тут мы эмулируем поиск, в реальности можно подключить ваш YouTube поиск)
        playlist = []
        for track_name in data.get("tracks", []):
            playlist.append({
                "title": track_name.split("-")[-1].strip() if "-" in track_name else track_name,
                "artist": track_name.split("-")[0].strip() if "-" in track_name else "Unknown",
                "query": track_name # Это пойдет в поиск YouTube
            })

        return {
            "dj_intro": data.get("intro", "Система готова. Поехали!"),
            "playlist": playlist
        }

    except Exception as e:
        print(f"[AI Error] {e}")
        return {"error": str(e)}

@app.post("/telegram")
async def telegram_webhook(request: Request):
    tg_app = request.app.state.tg_app
    try:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
    return {"ok": True}

# Mount the 'webapp' directory to serve static files at the root
app.mount("/", StaticFiles(directory="webapp", html=True), name="static")