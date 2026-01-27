import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
import os
import json
import subprocess
import shutil

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect
from telegram import Update, BotCommand
from telegram.ext import Application

from config import get_settings, Settings
from logging_setup import setup_logging
from radio import RadioManager
from youtube import YouTubeDownloader
from spotify import SpotifyService # <--- IMPORT ADDED
from handlers import setup_handlers
from cache_service import CacheService
from chat_service import ChatManager 

from gemini_init import HAS_GENAI 

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime(): return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("⚡ Aurora System Starting...")
    
    # --- ДИАГНОСТИКА ---
    logger.info("🛠 DIAGNOSTIC CHECK:")
    if shutil.which("node"): logger.info("✅ Node.js DETECTED")
    else: logger.error("❌ Node.js NOT FOUND")
    
    if shutil.which("ffmpeg"): logger.info("✅ FFmpeg DETECTED")
    else: logger.error("❌ FFmpeg NOT FOUND")

    if HAS_GENAI: logger.info("🧠 NLP Engine: ACTIVE (Gemini)")
    else: logger.warning("🧠 NLP Engine: INACTIVE")

    settings = get_settings()
    app.state.settings = settings
    
    os.makedirs(settings.DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(settings.TEMP_AUDIO_DIR, exist_ok=True)
    
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader
    
    # Инициализация Spotify (FIXED)
    spotify_service = SpotifyService(settings, downloader)
    app.state.spotify_service = spotify_service
    
    builder = Application.builder().token(settings.BOT_TOKEN).read_timeout(30).write_timeout(30)
    if settings.PROXY_URL: builder.proxy_url(settings.PROXY_URL)
    tg_app = builder.build()
    tg_app.bot_data['settings'] = settings

    radio_manager = RadioManager(bot=tg_app.bot, settings=settings, downloader=downloader)
    
    # Передаем spotify_service в хендлеры (FIXED)
    setup_handlers(
        app=tg_app, 
        radio=radio_manager, 
        settings=settings, 
        downloader=downloader,
        spotify_service=spotify_service 
    )
    
    commands = [
        BotCommand("radio", "🎲 Случайная волна"),
        BotCommand("play", "🔎 Найти трек"),
        BotCommand("stop", "🛑 Остановить"),
        BotCommand("admin", "⚙️ Настройки"),
        BotCommand("status", "📊 Статус")
    ]
    await tg_app.bot.set_my_commands(commands)
    
    await tg_app.initialize()
    await tg_app.start()
    
    if settings.WEBHOOK_URL:
        await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
        logger.info(f"🔗 Webhook: {settings.WEBHOOK_URL}")
    
    app.state.tg_app = tg_app
    app.state.radio_manager = radio_manager
    app.state.cache = cache
    
    yield
    
    await radio_manager.stop_all()
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str, request: Request):
    logger.info(f"[AI Web] Prompt: {prompt}")
    intro = await ChatManager.get_response(0, f"Intro for song: {prompt}", "User") or "Playing your track!"
    downloader = request.app.state.downloader
    tracks = await downloader.search(query=prompt, limit=10)
    return {"dj_intro": intro, "playlist": tracks}

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    settings = request.app.state.settings
    file_path = settings.DOWNLOADS_DIR / f"{video_id}.mp3"
    
    if file_path.exists() and file_path.stat().st_size > 20000:
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"error": "File not yet cached."})

@app.get("/api/health")
async def health(): return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist")
async def get_playlist(query: str, request: Request):
    downloader = request.app.state.downloader
    tracks = await downloader.search(query=query, limit=15)
    if tracks:
        for track in tracks:
            asyncio.create_task(downloader.download(track.identifier, track))
    return {"playlist": tracks}

@app.post("/telegram")
async def telegram_webhook(request: Request):
    tg_app = request.app.state.tg_app
    try:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        asyncio.create_task(tg_app.process_update(update))
    except (json.JSONDecodeError, ClientDisconnect): pass
    except Exception as e: logger.error(f"Webhook Error: {e!r}")
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")