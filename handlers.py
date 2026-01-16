from __future__ import annotations
import logging
import asyncio
import json
import random
from pathlib import Path

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.constants import ParseMode, ChatType
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)

from radio import RadioManager
from config import Settings, get_settings
from youtube import YouTubeDownloader
from chat_service import ChatManager
from ai_personas import PERSONAS
from ai_manager import AIManager
# Импортируем nlp
from nlp import analyze_message

def _get_debug_log_path():
    """Get path to debug log file, works on both Windows and Linux"""
    base_dir = Path(__file__).resolve().parent
    log_path = base_dir / ".cursor" / "debug.log"
    return str(log_path)

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
    """Безопасная отправка ответа"""
    # #region agent log
    try:
        import json
        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"handlers.py:61","message":"_do_chat_reply ENTRY","data":{"chat_id":chat_id,"text_preview":text[:50],"user_name":user_name},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    response = await ChatManager.get_response(chat_id, text, user_name)
    
    # #region agent log
    try:
        import json
        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"handlers.py:65","message":"_do_chat_reply got response","data":{"has_response":bool(response),"response_preview":response[:50] if response else None},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    
    # ЗАЩИТА ОТ CRASH: Если ответ пустой, ставим заглушку
    if not response or not response.strip():
        response = "..."
        
    # Проверка на JSON-команду от AI
    if "{" in response and "command" in response:
        try:
            data = json.loads(response[response.find("{"):response.rfind("}")+1])
            if data.get("command") == "radio":
                await _do_radio(chat_id, data.get("query", "random"), context, update)
                return
        except: pass
    
    try:
        await update.message.reply_text(response)
    except BadRequest as e:
        logger.error(f"Failed to send reply: {e}")
        # Если даже заглушка не отправилась (редкость), игнорируем

# --- HANDLER ---

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.effective_message.text
    chat_id = update.effective_chat.id
    
    if not message_text or len(message_text) < 2: return
    
    # Проверяем режим чата - если quiz, ответы идут сразу в AI
    current_mode = ChatManager.get_mode(chat_id)
    is_quiz_mode = current_mode == "quiz"
    
    # Проверяем, было ли последнее сообщение бота вопросом викторины (содержит ❓)
    # В этом случае ответ пользователя должен идти в чат, а не в NLP
    try:
        last_message = await context.bot.fetch_message(chat_id, update.effective_message.message_id - 1)
        is_quiz_question = last_message and last_message.from_user.id == context.bot.id and "❓" in (last_message.text or "")
    except:
        is_quiz_question = False
    
    is_private = update.effective_chat.type == ChatType.PRIVATE
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = any(w in message_text.lower() for w in ["аврора", "aurora", "бот", "dj"])

    # 1. Прямой диалог или режим викторины -> Сразу в чат
    if is_private or is_reply or is_mention or is_quiz_mode or is_quiz_question:
        await _do_chat_reply(chat_id, message_text, update.effective_user.first_name, context, update)
        return

    # 2. Неявный запрос -> Анализируем через NLP
    try:
        intent, query = await analyze_message(message_text)
        logger.info(f"[{chat_id}] NLP Analysis: '{message_text}' -> {intent} (query: '{query}')")
    except Exception as e:
        logger.error(f"[{chat_id}] NLP error: {e}, using default chat")
        intent, query = "chat", message_text  # Fallback на чат с оригинальным сообщением
    
    if intent == 'chat':
        await _do_chat_reply(chat_id, message_text, update.effective_user.first_name, context, update)
    elif intent == 'search':
        await _do_play(chat_id, query, context, update)
    elif intent == 'radio':
        await _do_radio(chat_id, query, context, update)

# --- ADMIN / COMMANDS ---
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяет реальный статус всех активных AI-провайдеров, делая тестовые запросы,
    включая проверку резервного канала Gemini.
    """
    msg = await update.message.reply_text("🔄 Диагностика AI-провайдеров...")

    from gemini_init import HAS_GENAI, generate_smart
    from ai_config import get_active_providers

    # --- Проверка основных провайдеров ---
    providers = get_active_providers()
    tasks = [AIManager.test_provider(p) for p in providers]
    results = await asyncio.gather(*tasks)

    provider_lines = []
    if not providers:
        provider_lines.append("• (нет активных провайдеров в конфиге)")
    else:
        for provider, status in zip(providers, results):
            provider_lines.append(f"• {provider.name}: {status}")
    
    provider_list = "\n".join(provider_lines)

    # --- Проверка резервного провайдера Gemini ---
    gemini_status = "❌ Inactive"
    if HAS_GENAI:
        try:
            # generate_smart - синхронная функция, запускаем в исполнителе
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: generate_smart("Ответь одним словом: OK"))
            
            if result and "OK" in result:
                gemini_status = "✅ OK"
            else:
                gemini_status = "⚠️ Bad Response"
        except Exception as e:
            logger.error(f"[Status Check] Gemini test failed: {e}")
            gemini_status = "❌ FAILED"

    # --- Формирование и отправка ответа ---
    text = f"""📊 *System Status*

*Основные AI провайдеры (онлайн-проверка):*
{provider_list}

*Резервный AI провайдер:*
• Gemini (Fallback): {gemini_status}
"""
    
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

async def test_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует AI провайдеров"""
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    msg = await update.message.reply_text("🔄 Тестирую AI провайдеры...")
    
    test_responses = []
    
    # Тестируем Gemini
    from gemini_init import HAS_GENAI
    if HAS_GENAI:
        try:
            from gemini_init import generate_smart
            result = generate_smart("Привет! Ответь коротко: 'OK'")
            if result and len(result.strip()) > 0:
                test_responses.append(f"✅ Gemini: OK ({len(result)} символов)")
            else:
                test_responses.append(f"⚠️ Gemini: пустой ответ")
        except Exception as e:
            test_responses.append(f"❌ Gemini: {str(e)[:50]}")
    else:
        test_responses.append(f"❌ Gemini: не настроен")
    
    # Показываем результат
    text = f"""🧪 *Тест AI*

{chr(10).join(test_responses)}

💡 Бот автоматически переключится на работающий провайдер."""
    
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_settings()
    
    # ПРОВЕРКА: Если пользователя нет в списке админов — игнорируем
    if user_id not in settings.ADMIN_ID_LIST:
        await update.message.reply_text("⛔️ У вас нет прав админа.")
        return

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
    user_id = query.from_user.id
    settings = get_settings() # Получаем настройки
    
    await query.answer()

    if query.data == "close_admin":
        await query.delete_message()
    elif query.data.startswith("set_mode|"):
        if user_id not in settings.ADMIN_ID_LIST:
            await query.answer("⛔️ Только для админа!", show_alert=True)
            return
        mode = query.data.split("|")[1]
        ChatManager.set_mode(update.effective_chat.id, mode)
        
        # Если включаем викторину - сразу запускаем первый вопрос
        if mode == "quiz":
            from chat_service import QuizManager
            first_question = QuizManager.start_quiz(update.effective_chat.id)
            await context.bot.send_message(update.effective_chat.id, f"🎮 *ВИКТОРИНА* 🎮\n\n{first_question}", parse_mode=ParseMode.MARKDOWN)
        else:
            greeting = GREETINGS.get(mode, ["Привет!"])[0]
            await context.bot.send_message(update.effective_chat.id, f"Режим изменен: {mode}\n\n{greeting}")

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
    app.add_handler(CommandHandler("test_ai", test_ai_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_callback))