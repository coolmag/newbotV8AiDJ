from __future__ import annotations
import logging
import os
import asyncio
from math import ceil
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)

from radio import RadioManager
from config import Settings
from catalog import MUSIC_CATALOG
from youtube import YouTubeDownloader
from keyboards import (
    get_track_search_keyboard, 
    get_pagination_keyboard, 
    get_main_menu_keyboard, 
    get_subcategory_keyboard
)

logger = logging.getLogger("handlers")

# ==================== КОМАНДЫ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start."""
    settings: Settings = context.application.settings
    base_url = settings.BASE_URL.strip() if settings.BASE_URL else ""
    
    text = (
        "🎧 *Музыкальный комбайн*\n\n"
        "Нажмите кнопку ниже, чтобы запустить веб-плеер или открыть меню жанров.\n\n"
        "/play <трек> - поиск\n"
        "/radio - случайная волна"
    )
    
    keyboard = []
    
    # --- БЕЗОПАСНАЯ КНОПКА ЗАПУСКА ВЕБ-ПЛЕЕРА ---
    if base_url.startswith("http"):
        if update.effective_chat.type == ChatType.PRIVATE:
            # В личке открываем WebApp (красиво)
            keyboard.append([InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=base_url))])
        else:
            # В группах открываем ссылку (безопасно, не крашит бота)
            keyboard.append([InlineKeyboardButton("🔗 Открыть плеер", url=base_url)])
    
    keyboard.append([InlineKeyboardButton("🗂 Открыть меню жанров", callback_data="main_menu_genres")])
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    elif update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /player"""
    if update.message.chat.type == ChatType.CHANNEL:
        await update.message.reply_text("Не работает в каналах.")
        return

    settings: Settings = context.application.settings
    url = settings.BASE_URL
    
    if update.effective_chat.type == ChatType.PRIVATE:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=url))]])
    else:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть плеер", url=url)]])
        
    await update.message.reply_text("👇 Плеер:", reply_markup=markup)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.stop(update.effective_chat.id)
    await update.message.reply_text("🛑 Плеер остановлен.")

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.skip(update.effective_chat.id)

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = " ".join(context.args)
    if not query_text:
        await update.message.reply_text("Пример: `/play Numb`", parse_mode=ParseMode.MARKDOWN)
        return

    msg = await update.message.reply_text(f"🔎 Ищу: *{query_text}*...", parse_mode=ParseMode.MARKDOWN)
    tracks = await context.application.downloader.search(query=query_text, search_mode='track', limit=1)
    
    if tracks:
        await msg.delete()
        await _send_track(context, update.effective_chat.id, tracks[0].identifier, update.effective_chat.type)
    else:
        await msg.edit_text("😕 Ничего не найдено.")

async def radio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎲 Запускаю случайную волну...")
    asyncio.create_task(context.application.radio_manager.start(
        chat_id=update.effective_chat.id, 
        query="random",
        chat_type=update.message.chat.type
    ))

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤔 Команда не распознана.")

# ==================== CALLBACKS ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu_start":
        await start(update, context)
    elif data == "main_menu_genres":
        await query.edit_message_text("🗂 *Жанры:*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_keyboard())
    elif data.startswith("cat|"):
        path_str = data[4:]
        if not path_str: await start(update, context); return
        await query.edit_message_text(f"💿 *{path_str.split('|')[-1]}:*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_subcategory_keyboard(path_str))
    elif data.startswith("play_cat|"):
        path = data[9:].split('|')
        try:
            current = MUSIC_CATALOG
            for p in path[:-1]: current = current[p]
            q = current[path[-1]]
        except: q = " ".join(path)
        await query.edit_message_text(f"🎵 Играет: *{path[-1]}*...", parse_mode=ParseMode.MARKDOWN)
        asyncio.create_task(context.application.radio_manager.start(query.message.chat.id, str(q), query.message.chat.type))
    elif data == "play_random":
        await query.edit_message_text("🎲 Рандом...")
        asyncio.create_task(context.application.radio_manager.start(query.message.chat.id, "random", query.message.chat.type))
    elif data.startswith("sel_track|"):
        await query.edit_message_text("⏳ Загрузка...")
        await _send_track(context, query.message.chat.id, data.split("|")[1], query.message.chat.type)
        await start(update, context)

# ==================== HELPERS ====================

async def _send_track(context: ContextTypes.DEFAULT_TYPE, chat_id: int, video_id: str, chat_type: str):
    dl = context.application.downloader
    res = await dl.download(video_id)
    if not res.success:
        await context.bot.send_message(chat_id, "❌ Ошибка загрузки")
        return
    
    try:
        if res.file_id:
            await context.bot.send_audio(chat_id, audio=res.file_id, title=res.track_info.title, performer=res.track_info.artist)
        elif res.file_path:
            with open(res.file_path, 'rb') as f:
                msg = await context.bot.send_audio(chat_id, f, title=res.track_info.title, performer=res.track_info.artist)
                if msg.audio: await dl.cache_file_id(video_id, msg.audio.file_id)
    finally:
        # Убрали os.unlink, теперь файл остается для Web Player
        pass

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
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
