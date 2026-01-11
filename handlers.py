from __future__ import annotations
import logging
import asyncio
import random

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
    base_url = settings.BASE_URL.strip() if settings.BASE_URL else ""
    
    # Исправленный текст (без лишних экранирований)
    text = (
        "🎧 *Aurora System v40*\n\n"
        "Я — твой AI-диджей.\n\n"
        "Команды:\n"
        "/play <трек> — найти песню\n"
        "/radio — запустить поток\n"
        "/mode — сменить характер\n"
        "/stop — стоп"
    )
    
    keyboard = []
    if base_url.startswith("http"):
        if update.effective_chat.type == ChatType.PRIVATE:
            keyboard.append([InlineKeyboardButton("🎧 Web Player", web_app=WebAppInfo(url=base_url))])
        else:
            keyboard.append([InlineKeyboardButton("🔗 Open Player", url=base_url)])
    
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    elif update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings: Settings = context.application.settings
    url = settings.BASE_URL
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open", url=url)]])
    await update.message.reply_text("👇 Player Link:", reply_markup=markup)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.stop(update.effective_chat.id)
    await update.message.reply_text("🛑 Playback stopped.")

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.skip(update.effective_chat.id)

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = " ".join(context.args)
    if not query_text:
        await update.message.reply_text("Usage: `/play Song Name`", parse_mode=ParseMode.MARKDOWN)
        return

    msg = await update.message.reply_text(f"🔎 Searching: *{query_text}*...", parse_mode=ParseMode.MARKDOWN)
    tracks = await context.application.downloader.search(query=query_text, search_mode='track', limit=1)
    
    if tracks:
        await msg.delete()
        await _send_track(context, update.effective_chat.id, tracks[0].identifier, update.effective_chat.type)
    else:
        await msg.edit_text("😕 Not found.")

async def radio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎲 Tuning frequency...")
    asyncio.create_task(context.application.radio_manager.start(
        chat_id=update.effective_chat.id, 
        query="random",
        chat_type=update.message.chat.type
    ))

# --- НОВЫЕ ХЕНДЛЕРЫ ---

async def set_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Смена личности бота."""
    if not context.args:
        modes = ", ".join(PERSONAS.keys())
        await update.message.reply_text(f"🎭 Режимы:\n{modes}\n\nПиши: `/mode toxic` (например)", parse_mode=ParseMode.MARKDOWN)
        return

    new_mode = context.args[0].lower()
    if ChatManager.set_mode(update.effective_chat.id, new_mode):
        await update.message.reply_text(f"✅ Режим: *{new_mode.upper()}*", parse_mode=ParseMode.MARKDOWN)
        # Приветствие в новом режиме
        response = await ChatManager.get_response(update.effective_chat.id, "Привет! Ты тут?", "System")
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Нет такого режима.")

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Болталка."""
    if not update.message or not update.message.text: return
    
    msg = update.message
    text = msg.text.lower()
    
    # Безопасное получение имени бота
    bot_username = "bot"
    if context.bot.username:
        bot_username = context.bot.username.lower()
    
    # Условия ответа: ЛС, Реплаи, Упоминание имени
    should_reply = (
        update.effective_chat.type == ChatType.PRIVATE or
        (msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id) or
        ("аврора" in text) or
        ("бот" in text) or
        (f"@{bot_username}" in text)
    )

    if should_reply:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        user_name = msg.from_user.first_name
        response = await ChatManager.get_response(update.effective_chat.id, msg.text, user_name)
        
        if response and response != "...":
            await msg.reply_text(response)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pass

# --- HELPERS ---

async def _send_track(context: ContextTypes.DEFAULT_TYPE, chat_id: int, video_id: str, chat_type: str):
    dl = context.application.downloader
    res = await dl.download(video_id)
    if not res.success:
        await context.bot.send_message(chat_id, "❌ Error downloading")
        return
    
    try:
        if res.file_path:
            with open(res.file_path, 'rb') as f:
                await context.bot.send_audio(chat_id, f, title=res.track_info.title, performer=res.track_info.artist)
    except Exception as e:
        logger.error(f"Send error: {e}")

def setup_handlers(app, radio, settings, downloader):
    app.downloader = downloader
    app.radio_manager = radio
    app.settings = settings
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("player", player_command))
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("radio", radio_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("skip", skip_command))
    
    # Регистрация чат-хендлеров
    app.add_handler(CommandHandler("mode", set_mode_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    
    app.add_handler(CallbackQueryHandler(button_callback))