from __future__ import annotations
import logging
import asyncio
import json
import random
import time
import psutil
import httpx 

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)

from radio import RadioManager
from config import Settings
from youtube import YouTubeDownloader
from chat_service import ChatManager, PERSONAS
from nlp import analyze_message # <-- НОВЫЙ ИМПОРТ

logger = logging.getLogger("handlers")

GREETINGS = {
    "default": ["Привет! Я снова я. 🎧", "Режим по умолчанию. Погнали!", "Снова в эфире!"],
    "toxic": ["Ну че, переключил? Теперь терпи.", "Ой, опять ты... Ладно, слушаю.", "Режим токсика активирован. 🙄"],
    "gop": ["Здарова, бродяга! Че каво?", "Ну че, посидим?", "Вечер в хату."],
    "chill": ["Вайб включен... 🌌", "Расслабься...", "Тишина и музыка..."],
    "quiz": ["Время викторины! 🎯", "Я готова задавать вопросы!"]
}

# --- ВНУТРЕННИЕ ИСПОЛНИТЕЛИ (REFACTORED LOGIC) ---

async def _do_play(chat_id: int, query: str, context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Ищет и отправляет трек. Основная логика для /play и NLP 'search'."""
    msg = await context.bot.send_message(chat_id, f"🔎 Ищу: *{query}*...", parse_mode=ParseMode.MARKDOWN)
    
    tracks = await context.application.downloader.search(query, limit=1)
    
    if tracks:
        await msg.delete()
        dl_res = await context.application.downloader.download(tracks[0].identifier)
        if dl_res.success and dl_res.file_path:
            with open(dl_res.file_path, 'rb') as f:
                await context.bot.send_audio(chat_id, f, title=dl_res.track_info.title, performer=dl_res.track_info.artist)
        else:
             await context.bot.send_message(chat_id, f"😕 Не удалось скачать трек: {dl_res.error}")
    else:
        await msg.edit_text("😕 Не нашла ничего по запросу.")

async def _do_radio(chat_id: int, query: str, context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Запускает радио. Основная логика для /radio и NLP 'radio'."""
    effective_query = query or "случайные популярные треки"
    await context.bot.send_message(chat_id, f"🎧 Окей! Включаю радио-волну: *{effective_query}*", parse_mode=ParseMode.MARKDOWN)
    asyncio.create_task(context.application.radio_manager.start(chat_id, effective_query))


# --- HANDLERS ---

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """НОВЫЙ ОБРАБОТЧИК ДЛЯ ОБЫЧНОГО ТЕКСТА (NLP)"""
    message_text = update.effective_message.text
    if not message_text or len(message_text) < 3: # Игнорируем слишком короткие сообщения
        return
        
    # --- Логика AI DJ из chat_service ---
    is_private = update.effective_chat.type == ChatType.PRIVATE
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = any(w in message_text.lower() for w in ["аврора", "aurora", "бот", "dj"])

    if is_private or is_reply or is_mention:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        user_name = update.effective_user.first_name
        response = await ChatManager.get_response(update.effective_chat.id, message_text, user_name)
        
        try:
            # Пытаемся распарсить JSON-команду от AI
            if "{" in response and "command" in response:
                data = json.loads(response[response.find("{"):response.rfind("}")+1])
                if data.get("command") == "radio":
                    query = data.get("query", "random")
                    await _do_radio(update.effective_chat.id, query, context, update)
                    return
        except json.JSONDecodeError:
            # Если не JSON, значит это обычный текстовый ответ
            await update.message.reply_text(response)
            return
        except Exception as e:
            logger.error(f"Error processing AI command: {e}")

        # Если это был не JSON, отправляем как текст
        if "{" not in response:
            await update.message.reply_text(response)
        return # Завершаем, если AI DJ ответил

    # --- Логика NLP для поиска музыки (если AI DJ не ответил) ---
    settings: Settings = context.application.settings
    # Не анализируем, если нет ключа Gemini - это будет просто тратой времени
    if not settings.GEMINI_API_KEY:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    intent, query = await analyze_message(message_text, settings)
    
    logger.info(f"NLP handled message. Intent: '{intent}', Query: '{query}'")
    
    if intent == 'search':
        await _do_play(update.effective_chat.id, query, context, update)
    elif intent == 'radio':
        await _do_radio(update.effective_chat.id, query, context, update)


# --- DIAGNOSTICS ---
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 *Запуск диагностики...*", parse_mode=ParseMode.MARKDOWN)
    report = ["📊 *System Status Report*"]
    mem = psutil.virtual_memory()
    report.append(f"🖥 *Server:* CPU {psutil.cpu_percent()}% | RAM {mem.percent}%")
    
    # Проверка AI провайдеров
    from ai_config import get_active_providers
    providers = get_active_providers()
    if providers:
        provider_names = ', '.join([p.name for p in providers])
        report.append(f"🧠 *AI Cascade:* ✅ {provider_names}")
    else:
        report.append(f"🧠 *AI Cascade:* ❌ No active providers")
    
    # Проверка NLP
    if context.application.settings.GEMINI_API_KEY:
        report.append("✨ *NLP Engine:* ✅ Gemini Active")
    else:
        report.append("✨ *NLP Engine:* ❌ Inactive (no key)")

    active_sessions = len(context.application.radio_manager._sessions)
    report.append(f"📻 *Radio:* {active_sessions} active streams")
    
    await status_msg.edit_text("\n".join(report), parse_mode=ParseMode.MARKDOWN)

# --- ADMIN PANEL ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_mode = ChatManager.get_mode(chat_id)
    text = f"🤖 Текущий режим AI DJ: *{current_mode.upper()}*\nВыберите личность:"
    keyboard = []
    row = []
    for mode in PERSONAS.keys():
        btn_text = f"✅ {mode.upper()}" if mode == current_mode else mode.upper()
        row.append(InlineKeyboardButton(btn_text, callback_data=f"set_mode|{mode}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="close_admin")])
    markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
    elif update.callback_query:
        try: await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        except BadRequest: pass

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

# --- COMMANDS (Теперь это обертки) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = context.application.settings
    url = settings.BASE_URL
    text = "🎧 *Aurora AI* (v9.0 NLP)\n\nПросто напиши, что хочешь послушать.\nНапример: 'включи фонк' или 'поставь queen a kind of magic'\n\n/radio — случайная волна\n/admin — сменить характер AI DJ"
    kb = []
    if url and url.startswith("http"):
        kb.append([InlineKeyboardButton("🌍 Web App", web_app=WebAppInfo(url=url))])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Пример: `/play Numb`", parse_mode=ParseMode.MARKDOWN)
        return
    await _do_play(update.effective_chat.id, query, context, update)

async def radio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    await _do_radio(update.effective_chat.id, query, context, update)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.stop(update.effective_chat.id)
    await update.message.reply_text("🛑 Стоп.")

def setup_handlers(app, radio, settings, downloader):
    app.downloader = downloader
    app.radio_manager = radio
    app.settings = settings
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("radio", radio_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("status", status_command))
    
    # ГЛАВНЫЙ ОБРАБОТЧИК ТЕКСТА
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    app.add_handler(CallbackQueryHandler(button_callback))
