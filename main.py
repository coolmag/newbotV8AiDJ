import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
import os
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update, BotCommand
from telegram.ext import Application

from config import get_settings, Settings
from logging_setup import setup_logging
from radio import RadioManager
from youtube import YouTubeDownloader
from handlers import setup_handlers
from cache_service import CacheService
from chat_service import ChatManager 

logger = logging.getLogger(__name__)

try:
    from google import genai
    logger.info("✅ Импорт google-genai прошёл успешно")
except ImportError:
    logger.critical("google-genai НЕ установлен! pip install google-genai==1.57.0")
    genai = None

if os.getenv("GEMINI_API_KEY"):
    logger.info("✅ GEMINI_API_KEY найден в окружении — Gemini готов")
else:
    logger.warning("GEMINI_API_KEY отсутствует — Gemini отключён")

_start_time = time.time()

def get_uptime(): return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("⚡ Application starting up...")
    settings = get_settings()
    
    # Ensure directories exist
    os.makedirs(settings.DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(settings.TEMP_AUDIO_DIR, exist_ok=True)
    
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    # Initialize Downloader
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader
    
    # Build Telegram App
    builder = Application.builder().token(settings.BOT_TOKEN)
    if settings.PROXY_URL: builder.proxy_url(settings.PROXY_URL)
    tg_app = builder.build()
    
    tg_app.bot_data['settings'] = settings

    radio_manager = RadioManager(bot=tg_app.bot, settings=settings, downloader=downloader)
    
    setup_handlers(app=tg_app, radio=radio_manager, settings=settings, downloader=downloader)
    
    commands = [
        BotCommand("radio", "🎲 Random Wave"),
        BotCommand("play", "🔎 Search Track"),
        BotCommand("admin", "🤖 AI Personality"),
        BotCommand("status", "📊 System Status"),
        BotCommand("stop", "🛑 Stop Music"),
    ]
    await tg_app.bot.set_my_commands(commands)
    
    await tg_app.initialize()
    await tg_app.start()
    
    # Webhook
    if settings.WEBHOOK_URL:
        await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
        logger.info(f"Webhook set to: {settings.WEBHOOK_URL}")
    
    app.state.tg_app = tg_app
    app.state.radio_manager = radio_manager
    app.state.cache = cache
    yield
    # Cleanup
    await radio_manager.stop_all()
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str, request: Request):
    logger.info(f"[AI] Web Request: {prompt}")
    intro = await ChatManager.get_response(0, f"Music for: {prompt}. Short DJ intro.", "Listener")
    if not intro or len(intro) > 100: intro = "Playing your vibes!"

    downloader = request.app.state.downloader
    tracks = await downloader.search(query=prompt, limit=10)
    return {"dj_intro": intro, "playlist": tracks}

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    downloader = request.app.state.downloader
    path = downloader._find_downloaded_file(video_id)
    if not path:
        res = await downloader.download(video_id)
        if res.success: path = res.file_path
    
    if path: return FileResponse(path)
    return JSONResponse(status_code=404, content={"error": "File not found"})

@app.get("/api/health")
async def health(): return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist")
async def get_playlist(query: str, request: Request):
    downloader = request.app.state.downloader
    tracks = await downloader.search(query=query, limit=15)
    return {"playlist": tracks}

@app.post("/telegram")
async def telegram_webhook(request: Request):
    tg_app = request.app.state.tg_app
    try: await tg_app.process_update(Update.de_json(await request.json(), tg_app.bot))
    except Exception as e: logger.error(f"Webhook error: {e}")
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")