import logging
import asyncio
import time
from datetime import timedelta
from contextlib import asynccontextmanager


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
