import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
from typing import List
import os
import json
import re

# Условный импорт Google (чтобы сервер не падал, если либы нет)
try:
    import google.generativeai as genai
    HAS_AI_LIB = True
except ImportError:
    HAS_AI_LIB = False
    print("⚠️ Google GenAI lib not found. AI features disabled.")

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

# Настройка AI
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY and HAS_AI_LIB:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"⚠️ Gemini Config Error: {e}")

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime():
    return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения."""
    setup_logging()
    logger.info("⚡ Application starting up...")
    
    settings: Settings = get_settings()
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    settings.TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader
    
    builder = Application.builder().token(settings.BOT_TOKEN)
    if settings.PROXY_URL:
        builder.proxy_url(settings.PROXY_URL)
        builder.get_updates_proxy_url(settings.PROXY_URL)
        
    tg_app = builder.build()
    
    radio_manager = RadioManager(
        bot=tg_app.bot,
        settings=settings,
        downloader=downloader
    )
    
    setup_handlers(
        app=tg_app,
        radio=radio_manager,
        settings=settings,
        downloader=downloader
    )
    
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
    
    webhook_url = settings.WEBHOOK_URL
    await tg_app.bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Bot started. Webhook: {webhook_url}")
    
    app.state.tg_app = tg_app
    app.state.radio_manager = radio_manager
    app.state.cache = cache
    
    yield
    
    logger.info("🛑 Shutting down...")
    await radio_manager.stop_all()
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()
    logger.info("✅ Shutdown complete.")

# ==========================================
# 🔥 ВАЖНО: Инициализация app ПЕРЕД роутами
# ==========================================
app = FastAPI(lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== РОУТЫ ====================

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str):
    if not GEMINI_KEY or not HAS_AI_LIB:
        return {"error": "AI Brain not connected"}

    print(f"[AI] Получен запрос: {prompt}")

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
        
        clean_text = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(clean_text)
        
        playlist = []
        for track_name in data.get("tracks", []):
            playlist.append({
                "title": track_name.split("-")[-1].strip() if "-" in track_name else track_name,
                "artist": track_name.split("-")[0].strip() if "-" in track_name else "AI Selection",
                "query": track_name
            })

        return {
            "dj_intro": data.get("intro", "Система готова. Поехали!"),
            "playlist": playlist
        }

    except Exception as e:
        print(f"[AI Error] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    
    file_path = downloader._find_downloaded_file(video_id)
    if file_path and file_path.exists():
        return FileResponse(file_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")
    
    logger.info(f"Audio file not found for {video_id}, attempting to download and wait...")
    
    await downloader.download(video_id)
    final_path = await downloader.wait_for_download_completion(video_id)
    
    if final_path:
         return FileResponse(final_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")

    return JSONResponse(status_code=404, content={"message": "Audio file not found"})

@app.get("/api/health")
def health():
    return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist", response_model=dict)
async def get_playlist(query: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    logger.info(f"API: Поиск плейлиста по запросу: '{query}'")
    try:
        tracks: List[TrackInfo] = await downloader.search(query=query, search_mode='track', limit=15)
        return {"playlist": tracks}
    except Exception as e:
        logger.error(f"API: Ошибка при поиске плейлиста: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error"})

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

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")