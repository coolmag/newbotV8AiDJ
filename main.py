# ... (начало файла без изменений)
import logging
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import timedelta
from typing import List
import os
import json
import re

# Условный импорт Google, чтобы сервер не падал при старте, если либы нет
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

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY and HAS_AI_LIB:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"⚠️ Gemini Config Error: {e}")

logger = logging.getLogger(__name__)
_start_time = time.time()

# ... (код lifespan без изменений) ...
# Вставьте сюда вашу функцию lifespan и создание app = FastAPI(...)

# --- AI ENDPOINT (Безопасная версия) ---
@app.get("/api/ai/dj")
async def ai_dj_generate(prompt: str):
    if not GEMINI_KEY or not HAS_AI_LIB:
        return {"error": "AI Brain not connected"}

    print(f"[AI] Получен запрос: {prompt}")

    system_instruction = """
    Ты — DJ Aurora. 
    1. Подбери 5 треков.
    2. Напиши интро.
    Верни JSON: {"intro": "...", "tracks": ["Artist - Title"]}
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(f"{system_instruction}\n\nЗапрос: {prompt}")
        
        clean_text = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(clean_text)
        
        playlist = []
        for track_name in data.get("tracks", []):
            playlist.append({
                "title": track_name,
                "artist": "AI Selection", # Упрощаем для поиска
                "query": track_name
            })

        return {
            "dj_intro": data.get("intro", "Поехали!"),
            "playlist": playlist
        }

    except Exception as e:
        print(f"[AI Error] {e}")
        # Возвращаем 500, но в JSON, чтобы фронт обработал
        return JSONResponse(status_code=500, content={"error": str(e)})

# ... (остальные эндпоинты telegram, health, audio без изменений) ...
