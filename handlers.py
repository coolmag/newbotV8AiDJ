from __future__ import annotations
import logging
import asyncio
import json

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

# --- ADMIN PANEL ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель управления ИИ."""
    current_mode = ChatManager.chat_modes[update.effective_chat.id]
    
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
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "close_admin":
        await query.delete_message()
        
    elif data.startswith("set_mode|"):
        new_mode = data.split("|")[1]
        ChatManager.set_mode(update.effective_chat.id, new_mode)
        await admin_command(update, context) # Обновляем галочку
        
        # Приветствие в новом режиме
        resp = await ChatManager.get_response(update.effective_chat.id, "Привет!", "System")
        if "{" not in resp:
            await context.bot.send_message(update.effective_chat.id, resp)

# --- STANDARD COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.application.settings
    url = settings.BASE_URL
    text = (
        "🎧 *Aurora System v46*\n\n"
        "Музыкальный ИИ-Ассистент.\n\n"
        "/radio — Эфир\n"
        "/play — Поиск\n"
        "/admin — Настройки ИИ"
    )
    kb = []
    if url and url.startswith("http"):
        if update.effective_chat.type == ChatType.PRIVATE:
            kb.append([InlineKeyboardButton("🎧 Web App", web_app=WebAppInfo(url=url))])
        else:
            kb.append([InlineKeyboardButton("🔗 Open Player", url=url)])
            
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

# --- CHAT HANDLER ---
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    chat_id = update.effective_chat.id
    
    is_quiz = ChatManager.chat_modes[chat_id] == "quiz"
    is_private = update.effective_chat.type == ChatType.PRIVATE
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = any(w in text.lower() for w in ["аврора", "aurora", "бот", "dj"])
    
    if is_private or is_reply or is_mention or is_quiz:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        user = update.effective_user.first_name
        response = await ChatManager.get_response(chat_id, text, user)
        
        try:
            if "{" in response and "command" in response:
                json_str = response[response.find("{"):response.rfind("}")+1]
                data = json.loads(json_str)
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
    app.add_handler(CommandHandler("admin", admin_command)) # ВОТ ОНА
    app.add_handler(CommandHandler("mode", admin_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    app.add_handler(CallbackQueryHandler(button_callback))