from __future__ import annotations
import logging
import asyncio
import json
import random

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
# Импортируем nlp
from nlp import analyze_message

logger = logging.getLogger("handlers")

GREETINGS = {
    "default": ["Привет! Я снова я. 🎧", "Режим по умолчанию. Погнали!", "Снова в эфире!"],
    "toxic": ["Ну че, переключил? Теперь терпи.", "Ой, опять ты... Ладно, слушаю.", "Режим токсика активирован. 🙄"],
    "gop": ["Здарова, бродяга! Че каво?", "Ну че, посидим?", "Вечер в хату."],
    "chill": ["Вайб включен... 🌌", "Расслабься...", "Тишина и музыка..."],
    "quiz": ["Время викторины! 🎯", "Я готова задавать вопросы!"]
}

# --- ВНУТРЕННИЕ ИСПОЛНИТЕЛИ ---

async def _do_play(chat_id: int, query: str, context: ContextTypes.DEFAULT_TYPE, update: Update):
    short_query = query[:200] + "..." if len(query) > 200 else query
    msg = await context.bot.send_message(
        chat_id, 
        f"🔎 Ищу: *{short_query}*...", 
        parse_mode=ParseMode.MARKDOWN,
        disable_notification=True
    )
    
    tracks = await context.application.downloader.search(query, limit=1)
    
    if tracks:
        await msg.delete()
        dl_res = await context.application.downloader.download(tracks[0].identifier)
        if dl_res.success and dl_res.file_path:
            with open(dl_res.file_path, 'rb') as f:
                await context.bot.send_audio(chat_id, f, title=dl_res.track_info.title, performer=dl_res.track_info.artist)
        else:
             await context.bot.send_message(chat_id, f"😕 Не удалось скачать трек: {dl_res.error_message}")
    else:
        await msg.edit_text("😕 Не нашла ничего по запросу.")

async def _do_radio(chat_id: int, query: str, context: ContextTypes.DEFAULT_TYPE, update: Update):
    effective_query = query or "случайные популярные треки"
    await context.bot.send_message(chat_id, f"🎧 Окей! Включаю радио-волну: *{effective_query}*", parse_mode=ParseMode.MARKDOWN)
    asyncio.create_task(context.application.radio_manager.start(chat_id, effective_query))

async def _do_chat_reply(chat_id: int, text: str, user_name: str, context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Отправляет текстовый ответ через ChatManager"""
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    response = await ChatManager.get_response(chat_id, text, user_name)
    
    # Проверяем, не вернул ли AI команду вместо текста
    if "{" in response and "command" in response:
        try:
            data = json.loads(response[response.find("{"):response.rfind("}")+1])
            if data.get("command") == "radio":
                await _do_radio(chat_id, data.get("query", "random"), context, update)
                return
        except: pass
    
    # Обычный ответ
    await update.message.reply_text(response)

# --- HANDLER ---

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.effective_message.text
    chat_id = update.effective_chat.id
    
    if not message_text or len(message_text) < 2: return
    
    is_private = update.effective_chat.type == ChatType.PRIVATE
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = any(w in message_text.lower() for w in ["аврора", "aurora", "бот", "dj"])

    # 1. Прямой диалог (Приват, Реплай, Меншн) -> Сразу в чат
    if is_private or is_reply or is_mention:
        await _do_chat_reply(chat_id, message_text, update.effective_user.first_name, context, update)
        return

    # 2. Неявный запрос -> Анализируем через NLP
    # (Это решает проблему "как дела?" в группе)
    
    loop = asyncio.get_event_loop()
    intent, query = await loop.run_in_executor(None, analyze_message, message_text)
    
    logger.info(f"[{chat_id}] NLP Analysis: '{message_text}' -> {intent}")
    
    if intent == 'chat':
        # Если NLP понял, что это просто болтовня - отвечаем
        await _do_chat_reply(chat_id, message_text, update.effective_user.first_name, context, update)
    elif intent == 'search':
        await _do_play(chat_id, query, context, update)
    elif intent == 'radio':
        await _do_radio(chat_id, query, context, update)

# --- ADMIN / COMMANDS ---
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from gemini_init import HAS_GENAI
    status = "✅ Active" if HAS_GENAI else "❌ Inactive"
    await update.message.reply_text(f"📊 System Status\nNLP (Gemini): {status}")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_mode = ChatManager.get_mode(chat_id)
    text = f"🤖 Режим AI: *{current_mode.upper()}*\nВыберите личность:"
    keyboard = []
    row = []
    for mode in PERSONAS.keys():
        btn_text = f"✅ {mode.upper()}" if mode == current_mode else mode.upper()
        row.append(InlineKeyboardButton(btn_text, callback_data=f"set_mode|{mode}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="close_admin")])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "close_admin":
        await query.delete_message()
    elif query.data.startswith("set_mode|"):
        mode = query.data.split("|")[1]
        ChatManager.set_mode(update.effective_chat.id, mode)
        await context.bot.send_message(update.effective_chat.id, f"Режим изменен: {mode}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎧 Aurora AI. Пиши запрос!")

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_play(update.effective_chat.id, " ".join(context.args), context, update)

async def radio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_radio(update.effective_chat.id, " ".join(context.args), context, update)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.application.radio_manager.stop(update.effective_chat.id)
    await context.bot.send_message(update.effective_chat.id, "🛑 Стоп.")

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_callback))