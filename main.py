import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
import os
import json
import re
import random

# --- G4F STABLE ---
import g4f

PROVIDERS = [
    g4f.Provider.GeekGpt,
    g4f.Provider.Liaobots,
    g4f.Provider.Chatgpt4o,
    g4f.Provider.Blackbox,
]

# Запасные фразы, чтобы ИИ всегда "говорил"
BACKUP_INTROS = [
    "В эфире Аврора. Лови волну.",
    "Специально для тебя — лучший саунд.",
    "Запускаю музыкальный поток.",
    "Система готова. Поехали.",
    "Только хиты, только хардкор.",
    "Настраиваюсь на твою частоту.",
    "Отличный выбор. Слушаем.",
    "Музыка для души и тела.",
    "Аврора на связи. Включаю.",
    "Заряжаю позитивом.",
]

async def get_ai_response(prompt: str) -> str:
    for provider in PROVIDERS:
        try:
            response = await g4f.ChatCompletion.create_async(
                model=g4f.models.gpt_35_turbo,
                messages=[{"role": "user", "content": prompt}],
                provider=provider,
                timeout=15, # Чуть меньше таймаут
            )
            if response: return str(response)
        except: continue
    return "" # Возвращаем пустоту, чтобы сработал fallback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
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

logger = logging.getLogger(__name__)
_start_time = time.time()

def get_uptime(): return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # НАДЕЖНАЯ ВЕРСИЯ LIFESPAN
    setup_logging()
    logger.info("⚡ Application starting up...")
    
    try:
        settings: Settings = get_settings()
    except Exception as e:
        logger.critical(f"FATAL CONFIG ERROR: {e}")
        raise e
    
    # CLEANUP ON START
    import shutil
    if os.path.exists(settings.DOWNLOADS_DIR):
        try:
            shutil.rmtree(settings.DOWNLOADS_DIR)
            logger.info("🧹 Downloads cleared.")
        except Exception as e:
            logger.error(f"Failed to clear downloads: {e}")
    
    os.makedirs(settings.DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(settings.TEMP_AUDIO_DIR, exist_ok=True)
    
    cache = CacheService(settings.CACHE_DB_PATH)
    await cache.initialize()
    
    downloader = YouTubeDownloader(settings, cache)
    app.state.downloader = downloader
    
    builder = Application.builder().token(settings.BOT_TOKEN)
    if settings.PROXY_URL: builder.proxy_url(settings.PROXY_URL)
    tg_app = builder.build()
    
    radio_manager = RadioManager(bot=tg_app.bot, settings=settings, downloader=downloader)
    setup_handlers(app=tg_app, radio=radio_manager, settings=settings, downloader=downloader)
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
    
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
    logger.info(f"[AI] Request: {prompt}")
    
    system_instruction = "Ты DJ Aurora. Подбери 5 треков. JSON: {'intro': '...', 'tracks': ['Artist - Title']}"
    full_prompt = f"{system_instruction}\n\nЗапрос: {prompt}"

    try:
        raw_response = await get_ai_response(full_prompt)
        
        json_match = re.search(r'{{.*}}', raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            # Если ИИ не ответил JSON-ом или молчит -> берем случайную фразу
            data = {
                "intro": random.choice(BACKUP_INTROS), 
                "tracks": [prompt]
            }

        # Если интро пустое, тоже заполняем
        if not data.get("intro"):
            data["intro"] = random.choice(BACKUP_INTROS)

        downloader = request.app.state.downloader
        final_playlist = []
        
        tracks = data.get("tracks", [])
        if not tracks: tracks = [prompt]

        for t in tracks:
            found = await downloader.search(query=t, limit=1)
            if found: final_playlist.extend(found)
            
        if not final_playlist:
             final_playlist = await downloader.search(query=prompt, limit=10)

        return {"dj_intro": data["intro"], "playlist": final_playlist}

    except Exception as e:
        logger.error(f"[AI Error] {e}")
        downloader = request.app.state.downloader
        tracks = await downloader.search(query=prompt, limit=10)
        return {"dj_intro": random.choice(BACKUP_INTROS), "playlist": tracks}

@app.get("/audio/{video_id}.mp3")
async def get_audio_file(video_id: str, request: Request):
    downloader = request.app.state.downloader
    
    # 1. Проверяем наличие файла
    path = downloader._find_downloaded_file(video_id)
    
    # 2. Если файла нет или он недокачан (.part)
    if not path or os.path.exists(str(path) + ".part"):
        logger.info(f"Downloading {video_id}...")
        
        # ВАЖНО: Метод download теперь сам ждет завершения
        res = await downloader.download(video_id)
        
        if res.success and res.file_path:
            path = res.file_path
        else:
            logger.error(f"Failed to stream {video_id}")
            return JSONResponse(status_code=404, content={"error": "Download failed"})

    # 3. Финальная проверка перед отдачей
    if path and path.exists() and path.stat().st_size > 1024:
        return FileResponse(
            path, 
            media_type="audio/mpeg", 
            headers={"Accept-Ranges": "bytes"}
        )
    
    return JSONResponse(status_code=404, content={"error": "File lost"})

@app.get("/api/health")
async def health(): return {"status": "ok", "uptime": get_uptime()}

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
    except Exception: pass
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")