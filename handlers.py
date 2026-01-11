from __future__ import annotations
import logging
import asyncio
import json
import random
import time
import psutil # Для проверки памяти

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)

from radio import RadioManager
from config import Settings
from youtube import YouTubeDownloader
from chat_service import ChatManager, PERSONAS

logger = logging.getLogger("handlers")

GREETINGS = {
    "default": ["Привет! Я снова я. 🎧", "Режим по умолчанию. Погнали!", "Снова в эфире!"],
    "toxic": ["Ну че, переключил? Теперь терпи.", "Ой, опять ты... Ладно, слушаю.", "Режим токсика активирован. 🙄"],
    "gop": ["Здарова, бродяга! Че каво?", "Ну че, посидим, пообщаемся?", "Вечер в хату."],
    "chill": ["Вайб включен... 🌌", "Расслабься, я с тобой.", "Тишина и музыка..."],
    "quiz": ["Время викторины! 🎯 Кто тут самый умный?", "Я готова задавать вопросы!", "Погнали играть!"]
}

# --- DIAGNOSTICS ---
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 *Диагностика систем...*", parse_mode=ParseMode.MARKDOWN)
    
    report = ["📊 *System Status Report*"]
    
    # 1. Server Load
    mem = psutil.virtual_memory()
    report.append(f"🖥 *Server:* CPU {psutil.cpu_percent()}% | RAM {mem.percent}%")
    
    # 2. AI Latency Check
    start_ai = time.time()
    ai_resp = await ChatManager.get_response(update.effective_chat.id, "ping", "Admin")
    ai_time = round(time.time() - start_ai, 2)
    ai_status = "✅ OK" if "{" not in ai_resp and len(ai_resp) > 0 else "⚠️ Slow/Fallback"
    if ai_time > 5: ai_status = "❌ Timeout"
    report.append(f"🧠 *AI Core:* {ai_status} ({ai_time}s)")
    
    # 3. Radio State
    active_sessions = len(context.application.radio_manager._sessions)
    report.append(f"📻 *Radio:* {active_sessions} active streams")
    
    await msg.edit_text("\n".join(report), parse_mode=ParseMode.MARKDOWN)

# --- ADMIN PANEL ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_mode = ChatManager.get_mode(chat_id)
    text = (
        "🛠 *Панель Администратора*\n\n"
        f"🤖 Текущий режим: *{current_mode.upper()}*\n"
        "Выберите личность:"
    )
    keyboard = []
    row = []
    for mode in PERSONAS.keys():
        btn_text = f"✅ {mode.upper()}" if mode == current_mode else mode.upper()
        row.append(InlineKeyboardButton(btn_text, callback_data=f"set_mode|{mode}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="close_admin")])
    
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "close_admin":
        await query.delete_message()
        
    elif data.startswith("set_mode|"):
        new_mode = data.split("|")[1]
        ChatManager.set_mode(update.effective_chat.id, new_mode)
        await admin_command(update, context)
        greeting = random.choice(GREETINGS.get(new_mode, GREETINGS["default"]))
        await context.bot.send_message(update.effective_chat.id, greeting)

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = context.application.settings
    url = settings.BASE_URL
    text = "🎧 *Aurora v50*\n\n/radio — Эфир\n/admin — Настройки ИИ\n/status — Диагностика"
    kb = []
    if url and url.startswith("http"):
        kb.append([InlineKeyboardButton("🎧 Web App", web_app=WebAppInfo(url=url))])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Пример: `/play Numb`", parse_mode=ParseMode.MARKDOWN)
        return
    msg = await update.message.reply_text(f"🔎 Ищу: *{query}*...", parse_mode=ParseMode.MARKDOWN)
    tracks = await context.application.downloader.search(query, limit=1)
    if tracks:
        await msg.delete()
        await _send_track(context, update.effective_chat.id, tracks[0].identifier)
    else:
        await msg.edit_text("😕 Не нашла.")

async def radio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎲 Настраиваю частоту...")
    asyncio.create_task(context.application.radio_manager.start(update.effective_chat.id, "random"))

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.stop(update.effective_chat.id)
    await update.message.reply_text("🛑 Стоп.")

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.skip(update.effective_chat.id)

async def player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.application.settings.BASE_URL
    await update.message.reply_text("👇 Плеер:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open", url=url)]]))

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    chat_id = update.effective_chat.id
    
    is_private = update.effective_chat.type == ChatType.PRIVATE
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = any(w in text.lower() for w in ["аврора", "aurora", "бот", "dj"])
    
    if is_private or is_reply or is_mention:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        user = update.effective_user.first_name
        response = await ChatManager.get_response(chat_id, text, user)
        
        try:
            if "{" in response and "command" in response:
                data = json.loads(response[response.find("{"):response.rfind("}")+1])
                if data.get("command") == "radio":
                    q = data.get("query", "random")
                    await update.message.reply_text(f"🎧 Окей! Ставлю: *{q}*", parse_mode=ParseMode.MARKDOWN)
                    asyncio.create_task(context.application.radio_manager.start(chat_id, q))
                    return
        except: pass

        if response and "{" not in response:
            await update.message.reply_text(response)

async def _send_track(context, chat_id, video_id):
    dl = context.application.downloader
    res = await dl.download(video_id)
    if res.success and res.file_path:
        with open(res.file_path, 'rb') as f:
            await context.bot.send_audio(chat_id, f, title=res.track_info.title, performer=res.track_info.artist)

def setup_handlers(app, radio, settings, downloader):
    app.downloader = downloader
    app.radio_manager = radio
    app.settings = settings
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("radio", radio_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("skip", skip_command))
    app.add_handler(CommandHandler("player", player_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("mode", admin_command))
    app.add_handler(CommandHandler("status", status_command)) # DIAGNOSTICS
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    app.add_handler(CallbackQueryHandler(button_callback))