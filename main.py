import logging
import asyncio
import time
import os
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import Application

# Local imports
from config import get_settings, Settings
from logging_setup import setup_logging
from dependencies import get_settings_dep
from cache_service import CacheService
from youtube import YouTubeDownloader
from radio import RadioManager
from handlers import setup_handlers

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime():
    return str(timedelta(seconds=int(time.time() - _start_time)))

async def cleanup_task(settings: Settings):
    """Фоновая задача для очистки старых файлов."""
    while True:
        try:
            await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)
            logger.info("🧹 Starting cleanup task...")
            
            now = time.time()
            deleted_count = 0
            
            if settings.DOWNLOADS_DIR.exists():
                for f in settings.DOWNLOADS_DIR.iterdir():
                    if f.is_file():
                        # Проверяем время последней модификации
                        if now - f.stat().st_mtime > settings.FILE_MAX_AGE_SECONDS:
                            try:
                                f.unlink()
                                deleted_count += 1
                            except Exception as e:
                                logger.error(f"Failed to delete {f}: {e}")
            
            logger.info(f"🧹 Cleanup finished. Deleted {deleted_count} files.")
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
            await asyncio.sleep(60) # Ждем минуту перед повторной попыткой при ошибке

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
    app.state.radio_manager = radio_manager # Сохраняем для доступа через API если нужно
    
    setup_handlers(app=tg_app, radio=radio_manager, settings=settings, downloader=downloader)
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
    
    app.state.tg_app = tg_app
    
    # Запуск задачи очистки
    cleanup_future = asyncio.create_task(cleanup_task(settings))
    
    yield
    
    # Shutdown
    cleanup_future.cancel()
    await radio_manager.stop_all()
    await tg_app.stop()
    await cache.close()

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

@app.get("/audio/{video_id}")
async def stream_audio(video_id: str, request: Request):
    downloader: YouTubeDownloader = request.app.state.downloader
    # Проверяем, есть ли файл, если нет — качаем
    res = await downloader.download(video_id)
    if res.success and res.file_path and res.file_path.exists():
        # Обновляем время доступа к файлу, чтобы cleanup не удалил его
        try:
            os.utime(res.file_path, None)
        except: pass
        return FileResponse(res.file_path, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="Audio not found")

@app.get("/api/health")
async def health():
    return {"status": "ok", "uptime": get_uptime()}

@app.get("/api/player/playlist")
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
        logger.error(f"Webhook error: {e}", exc_info=True)
    return {"ok": True}

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")