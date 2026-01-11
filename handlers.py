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
from chat_service import ChatManager
from ai_personas import PERSONAS

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

async def set_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Смена личности бота. Только для админов."""
    user_id = update.effective_user.id
    settings: Settings = context.application.settings
    
    # Простая проверка админа (можно усложнить)
    # Если ADMIN_IDS пуст в конфиге, то разрешаем всем (для тестов)
    if settings.ADMIN_ID_LIST and user_id not in settings.ADMIN_ID_LIST:
        await update.message.reply_text("⛔️ Access Denied. Ты не Архитектор.")
        return

    if not context.args:
        modes = ", ".join(PERSONAS.keys())
        await update.message.reply_text(f"🎭 Доступные режимы:\n{modes}\n\nПример: `/mode toxic`")
        return

    new_mode = context.args[0].lower()
    if ChatManager.set_mode(update.effective_chat.id, new_mode):
        await update.message.reply_text(f"✅ Личность изменена на: *{new_mode.upper()}*", parse_mode=ParseMode.MARKDOWN)
        # Бот сразу реагирует на смену
        response = await ChatManager.get_response(update.effective_chat.id, "Привет, ты тут?", "System")
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Нет такого режима.")

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка болтовни."""
    if not update.message or not update.message.text: return
    
    msg = update.message
    text = msg.text.lower()
    bot_username = context.bot.username.lower() if context.bot.username else "bot"
    
    # Триггеры для ответа:
    # 1. Личное сообщение (ЛС)
    # 2. Ответ (Reply) на сообщение бота
    # 3. Упоминание имени ("аврора", "бот")
    should_reply = (
        update.effective_chat.type == ChatType.PRIVATE or
        (msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id) or
        ("аврора" in text) or
        (f" @{bot_username}" in text)
    )

    if should_reply:
        # Показываем "печатает..."
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        user_name = msg.from_user.first_name
        response = await ChatManager.get_response(update.effective_chat.id, msg.text, user_name)
        
        # Если ответ есть - шлем
        if response and response != "...":
            await msg.reply_text(response)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # (Оставил заглушку, так как логика кнопок была простой)
    pass

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
    
    # НОВЫЕ ХЕНДЛЕРЫ
    app.add_handler(CommandHandler("mode", set_mode_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    
    app.add_handler(CallbackQueryHandler(button_callback))
