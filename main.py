import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
from typing import List
import os
import json
import re

# Стабильный импорт
HAS_AI_LIB = False
try:
    import google.generativeai as genai
    HAS_AI_LIB = True
except ImportError:
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

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY and HAS_AI_LIB:
    try:
        genai.configure(api_key=GEMINI_KEY)
        logger = logging.getLogger(__name__)
        logger.info("🧠 Gemini AI (Stable) connected.")
    except Exception as e:
        print(f"⚠️ Gemini Config Error: {e}")
        HAS_AI_LIB = False

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime():
    return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
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
        
    tg_app = builder.build()
    
    radio_manager = RadioManager(bot=tg_app.bot, settings=settings, downloader=downloader)
    
    setup_handlers(app=tg_app, radio=radio_manager, settings=settings, downloader=downloader)
    
    await tg_app.initialize()
    await tg_app.start()
    
    webhook_url = settings.WEBHOOK_URL
    await tg_app.bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Bot started. Webhook: {webhook_url}")
    
    app.state.tg_app = tg_app
    app.state.radio_manager = radio_manager
    app.state.cache = cache
    
    yield
    
    await radio_manager.stop_all()
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str, request: Request):
    """
    Генерация плейлиста (Stable).
    """
    if not HAS_AI_LIB or not GEMINI_KEY:
        downloader: YouTubeDownloader = request.app.state.downloader
        tracks = await downloader.search(query=prompt + " music", limit=10)
        return {"dj_intro": "", "playlist": tracks} # Пустое интро, чтобы не болтал лишнего

    logger.info(f"[AI] Generating for: {prompt}")

    system_instruction = """
    Ты — DJ Aurora.
    Твоя задача:
    1. Подобрать 5 треков (Artist - Title) под настроение пользователя.
    2. Написать ОЧЕНЬ короткую фразу (Intro) на русском языке (максимум 5-6 слов).
    
    Пример ответа (JSON):
    {"intro": "Включаю режим ночного драйва.", "tracks": ["Kavinsky - Nightcall", "The Weeknd - Blinding Lights"]}
    """

    try:
        # Используем gemini-pro (она есть везде) или flash
        # Пробуем Flash, если нет - Pro
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(f"{system_instruction}\n\nЗапрос: {prompt}")
        except:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(f"{system_instruction}\n\nЗапрос: {prompt}")
        
        clean_text = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(clean_text)
        
        tracks_query = data.get("tracks", [])
        intro = data.get("intro", "Поиск завершен.")
        
        downloader: YouTubeDownloader = request.app.state.downloader
        final_playlist = []
        
        for track_name in tracks_query:
            found = await downloader.search(query=track_name, limit=1)
            if found: final_playlist.extend(found)
        
        if not final_playlist:
             final_playlist = await downloader.search(query=prompt, limit=10)

        return {"dj_intro": intro, "playlist": final_playlist}

    except Exception as e:
        logger.error(f"[AI Error] {e}")
        downloader: YouTubeDownloader = request.app.state.downloader
        tracks = await downloader.search(query=prompt, limit=10)
        # Возвращаем пустую строку в интро, чтобы он молчал при ошибке
        return {"dj_intro": "", "playlist": tracks}

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    file_path = downloader._find_downloaded_file(video_id)
    if file_path and file_path.exists():
        return FileResponse(file_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")
    
    await downloader.download(video_id)
    final_path = await downloader.wait_for_download_completion(video_id)
    
    if final_path:
        return FileResponse(final_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")
    return JSONResponse(status_code=404, content={"message": "Not found"})

@app.get("/api/health")
async def health(): return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist", response_model=dict)
async def get_playlist(query: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    tracks = await downloader.search(query=query, search_mode='track', limit=15)
    return {"playlist": tracks}

@app.post("/telegram")
async def telegram_webhook(request: Request):
    tg_app = request.app.state.tg_app
    try:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")
