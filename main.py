import logging
import asyncio
import time
from datetime import timedelta
from typing import List
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from telegram import Update
from telegram.ext import Application

from config import get_settings, Settings
from logging_setup import setup_logging
from radio import RadioManager
from youtube import YouTubeDownloader
from handlers import setup_handlers
from cache_service import CacheService
from models import TrackInfo

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime():
    return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader
    
    builder = Application.builder().token(settings.BOT_TOKEN)
    tg_app = builder.build()
    
    radio_manager = RadioManager(bot=tg_app.bot, settings=settings, downloader=downloader)
    
    setup_handlers(app=tg_app, radio=radio_manager, settings=settings, downloader=downloader)
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
    
    app.state.tg_app = tg_app
    yield
    await radio_manager.stop_all()
    await tg_app.stop()
    await cache.close()

app = FastAPI(lifespan=lifespan)

# --- ЭТОТ БЛОК БЫЛ ПРОПУЩЕН РАНЬШЕ: Стриминг аудио для веб-плеера ---
@app.get("/audio/{video_id}")
async def stream_audio(video_id: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    # Проверяем, есть ли файл, если нет — качаем
    res = await downloader.download(video_id)
    if res.success and res.file_path and res.file_path.exists():
        return FileResponse(res.file_path, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio not found")

@app.get("/api/player/playlist")
async def get_playlist(query: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    tracks = await downloader.search(query=query, search_mode='track', limit=15)
    return {"playlist": tracks}

@app.post("/telegram")
async def telegram_webhook(request: Request):
    tg_app = request.app.state.tg_app
    data = await request.json()
    await tg_app.process_update(Update.de_json(data, tg_app.bot))
    return {"ok": True}

@app.get("/")
async def root():
    return RedirectResponse(url="/webapp/index.html")

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")
