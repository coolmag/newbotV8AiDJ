import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
import os
import json
import re

# --- G4F STABLE CORE ---
import g4f

# Актуальный список провайдеров на 2026 (g4f 0.3.x)
PROVIDERS = [
    g4f.Provider.GeekGpt,
    g4f.Provider.Liaobots,
    g4f.Provider.Chatgpt4o,  # Исправлено имя!
    g4f.Provider.Blackbox,   # Добавил Blackbox (очень стабильный)
    g4f.Provider.FreeGpt,
]

async def get_ai_response(prompt: str) -> str:
    for provider in PROVIDERS:
        try:
            response = await g4f.ChatCompletion.create_async(
                model=g4f.models.gpt_35_turbo,
                messages=[{"role": "user", "content": prompt}],
                provider=provider,
                timeout=20,
            )
            # Проверка на пустой ответ
            if not response: continue
            return str(response)
        except:
            continue
            
    # Резервный ответ
    return '{"intro": "Связь с космосом прервана. Включаю музыку.", "tracks": []}'

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
    
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    settings.TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    
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
    fallback_intro = "Принято. Включаю музыку."
    logger.info(f"[AI] Request: {prompt}")
    
    system_instruction = "Ты DJ Aurora. Подбери 5 треков. JSON: {'intro': '...', 'tracks': ['Artist - Title']}"
    full_prompt = f"{system_instruction}\n\nЗапрос: {prompt}"

    try:
        raw_response = await get_ai_response(full_prompt)
        
        # Чистка JSON
        json_match = re.search(r'{{.*}}', raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            # Если провайдер вернул текст, а не JSON
            # Пытаемся извлечь треки, если они разделены новой строкой
            lines = [l.strip() for l in raw_response.split('\n') if l.strip() and '-' in l]
            if lines:
                data = {"intro": "Готово.", "tracks": lines[:5]}
            else:
                data = {"intro": "Готово.", "tracks": [prompt]}

        downloader = request.app.state.downloader
        final_playlist = []
        
        tracks = data.get("tracks", [])
        if not tracks: tracks = [prompt]

        for t in tracks:
            found = await downloader.search(query=t, limit=1)
            if found: final_playlist.extend(found)
            
        if not final_playlist:
             final_playlist = await downloader.search(query=prompt, limit=10)

        return {"dj_intro": data.get("intro", fallback_intro), "playlist": final_playlist}

    except Exception as e:
        logger.error(f"[AI Error] {e}")
        downloader = request.app.state.downloader
        tracks = await downloader.search(query=prompt, limit=10)
        return {"dj_intro": "Сбой нейросети.", "playlist": tracks}

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
