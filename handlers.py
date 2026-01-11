from __future__ import annotations
import logging
import asyncio

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)

from radio import RadioManager
from config import Settings
from youtube import YouTubeDownloader
from chat_service import ChatManager
from ai_personas import PERSONAS

logger = logging.getLogger("handlers")

# --- КОМАНДЫ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.application.settings
    url = settings.BASE_URL
    text = (
        "🎧 *Aurora System v42*\n\n"
        "Я — твой AI-диджей.\n\n"
        "/radio — Поток\n/mode — Личность\n/play — Поиск"
    )
    kb = []
    if url and url.startswith("http"):
        if update.effective_chat.type == ChatType.PRIVATE:
            kb.append([InlineKeyboardButton("🎧 Web App", web_app=WebAppInfo(url=url))])
        else:
            kb.append([InlineKeyboardButton("🔗 Open Player", url=url)])
            
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

# ВОТ ОНА, ПОТЕРЯННАЯ ФУНКЦИЯ
async def player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.application.settings
    url = settings.BASE_URL
    kb = [[InlineKeyboardButton("🔗 Open Player", url=url)]]
    await update.message.reply_text("👇 Ссылка на плеер:", reply_markup=InlineKeyboardMarkup(kb))

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.stop(update.effective_chat.id)
    await update.message.reply_text("🛑 Стоп.")

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.skip(update.effective_chat.id)

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

# --- CHAT & AI ---

async def set_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        modes = ", ".join(PERSONAS.keys())
        await update.message.reply_text(f"🎭 Режимы: {modes}\nПример: `/mode toxic`", parse_mode=ParseMode.MARKDOWN)
        return
    mode = context.args[0].lower()
    if ChatManager.set_mode(update.effective_chat.id, mode):
        await update.message.reply_text(f"✅ Режим: *{mode.upper()}*", parse_mode=ParseMode.MARKDOWN)
        resp = await ChatManager.get_response(update.effective_chat.id, "Привет!", "System")
        await update.message.reply_text(resp)
    else:
        await update.message.reply_text("❌ Нет такого режима.")

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    chat_type = update.effective_chat.type
    
    # Логируем
    logger.info(f"Msg from {chat_type}: {text}")

    should_reply = False
    if chat_type == ChatType.PRIVATE:
        should_reply = True
    else:
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        is_mention = ("аврора" in text.lower()) or ("бот" in text.lower())
        if is_reply or is_mention:
            should_reply = True

    if should_reply:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        user = update.effective_user.first_name
        response = await ChatManager.get_response(update.effective_chat.id, text, user)
        await update.message.reply_text(response)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

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
    app.add_handler(CommandHandler("player", player_command)) # Теперь работает
    app.add_handler(CommandHandler("mode", set_mode_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
