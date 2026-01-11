import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
import os
import json
import re
import random

# --- G4F SAFE IMPORT ---
import g4f

# БЕЗОПАСНАЯ СБОРКА ПРОВАЙДЕРОВ
# Мы не пишем g4f.Provider.GeekGpt напрямую, чтобы не упасть при старте
POSSIBLE_PROVIDERS = [
    'GeekGpt', 'GeekGPT', 
    'Liaobots', 
    'Blackbox', 
    'Chatgpt4o', 'ChatgptAi',
    'FreeGpt', 'Mssagr',
    'Hashnode'
]

WORKING_PROVIDERS = []
for name in POSSIBLE_PROVIDERS:
    if hasattr(g4f.Provider, name):
        WORKING_PROVIDERS.append(getattr(g4f.Provider, name))

logger = logging.getLogger(__name__)

async def get_ai_response(prompt: str) -> str:
    # Если список пуст, пробуем без указания провайдера (авто-выбор)
    providers_to_try = WORKING_PROVIDERS if WORKING_PROVIDERS else [None]
    
    for provider in providers_to_try:
        try:
            # Для старых версий g4f
            response = await g4f.ChatCompletion.create_async(
                model=g4f.models.gpt_35_turbo,
                messages=[{"role": "user", "content": prompt}],
                provider=provider,
                timeout=15,
            )
            if response: return str(response)
        except: continue
        
    return ""

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

_start_time = time.time()
def get_uptime(): return str(timedelta(seconds=int(time.time() - _start_time)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("⚡ Application starting up...")
    try: settings = get_settings()
    except: settings = Settings()
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

app = FastAPI(lifespan=app)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str, request: Request):
    logger.info(f"[AI] Request: {prompt}")
    
    # Резервные фразы
    BACKUP_INTROS = [
        "Включаю музыку.", "Погнали.", "Лови вайб.", 
        "Специально для тебя.", "Аврора в деле.", "Музыка нас связала."
    ]
    
    try:
        system = "Ты DJ Aurora. Подбери 5 треков. JSON: {'intro': '...', 'tracks': ['Artist - Title']}"
        full_prompt = f"{system}\n\nЗапрос: {prompt}"
        
        raw_response = await get_ai_response(full_prompt)
        
        json_match = re.search(r'{{.*}}', raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = {"intro": random.choice(BACKUP_INTROS), "tracks": [prompt]}

        if not data.get("intro"): data["intro"] = random.choice(BACKUP_INTROS)

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
    path = downloader._find_downloaded_file(video_id)
    if path: return FileResponse(path)
    res = await downloader.download(video_id)
    if res.success and res.file_path: return FileResponse(res.file_path)
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
    except: pass
    return {"ok": True}

app.mount("/", StaticFiles(directory="webapp", html=True), name="static")
