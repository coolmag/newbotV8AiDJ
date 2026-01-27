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
    
    # --- ДИАГНОСТИКА ОКРУЖЕНИЯ (НОВОЕ) ---
    logger.info("🛠 DIAGNOSTIC CHECK:")
    
    # 1. Проверка Node.js
    node_path = shutil.which("node") or shutil.which("nodejs")
    if node_path:
        try:
            v = subprocess.check_output([node_path, "--version"]).decode().strip()
            logger.info(f"✅ Node.js DETECTED: {v} at {node_path}")
        except Exception as e:
            logger.error(f"⚠️ Node.js found but failed: {e}")
    else:
        logger.error("❌ Node.js NOT FOUND! YouTube playback will fail.")

    # 2. Проверка FFmpeg
    if shutil.which("ffmpeg"):
        logger.info(f"✅ FFmpeg DETECTED")
    else:
        logger.error("❌ FFmpeg NOT FOUND!")
    # --------------------------------------

    if HAS_GENAI:
        logger.info("🧠 NLP Engine: ACTIVE (Gemini)")
    else:
        logger.warning("🧠 NLP Engine: INACTIVE (Check Logs/Env)")

    settings = get_settings()
    app.state.settings = settings
    
    # Ensure directories
    os.makedirs(settings.DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(settings.TEMP_AUDIO_DIR, exist_ok=True)
    
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader
    
    # Build Telegram App
    builder = Application.builder().token(settings.BOT_TOKEN).read_timeout(30).write_timeout(30)
    if settings.PROXY_URL: builder.proxy_url(settings.PROXY_URL)
    tg_app = builder.build()
    tg_app.bot_data['settings'] = settings

    radio_manager = RadioManager(bot=tg_app.bot, settings=settings, downloader=downloader)
    
    # Setup Handlers
    setup_handlers(app=tg_app, radio=radio_manager, settings=settings, downloader=downloader)
    
    # Commands
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
    
    # Shutdown
    await radio_manager.stop_all()
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- ENDPOINTS ---

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str, request: Request):
    logger.info(f"[AI Web] Prompt: {prompt}")
    intro = await ChatManager.get_response(0, f"Intro for song: {prompt}", "User")
    if not intro: intro = "Playing your track!"
    
    downloader = request.app.state.downloader
    tracks = await downloader.search(query=prompt, limit=10)
    return {"dj_intro": intro, "playlist": tracks}

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    settings = request.app.state.settings
    
    # Ищем только готовый, сконвертированный MP3 файл
    file_path = settings.DOWNLOADS_DIR / f"{video_id}.mp3"
    
    if file_path.exists() and file_path.stat().st_size > 20000:
        return FileResponse(file_path)
        
    # Если файла нет, мгновенно отвечаем 404, не пытаясь скачивать
    return JSONResponse(status_code=404, content={"error": "File not yet cached. Please wait and try again."})

@app.get("/api/health")
async def health(): return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist")
async def get_playlist(query: str, request: Request):
    downloader = request.app.state.downloader
    tracks = await downloader.search(query=query, limit=15)
    
    # --- PRE-CACHING ---
    # Запускаем скачивание в фоне для всех найденных треков
    if tracks:
        logger.info(f"Pre-caching {len(tracks)} tracks for query: '{query}'")
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
    except json.JSONDecodeError:
        logger.warning("Webhook received empty or invalid JSON. Likely a webhook validation ping.")
    except ClientDisconnect:
        logger.warning("Client disconnected before request body was read. Likely a webhook validation ping.")
    except Exception as e:
        logger.error(f"Webhook Update Error: {e!r}", exc_info=True)
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")