import logging
import json
from typing import Tuple, Optional

# Импорт должен быть google.generativeai
try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Импортируем глобальные флаги из main.py
from gemini_init import HAS_GENAI 

logger = logging.getLogger(__name__)

def _heuristic_fallback(message: str) -> Tuple[str, str]:
    """Простая логика, если AI сломался."""
    msg_lower = message.lower().strip()
    
    # Ключевые слова для музыки
    music_triggers = ['play', 'включи', 'поставь', 'найди', 'играй', 'track', 'song', 'песня', 'трек']
    
    # Если есть явная команда -> поиск
    if any(trigger in msg_lower for trigger in music_triggers):
        # Пытаемся вычленить запрос (очень грубо)
        return "search", message

    # Если сообщение длинное (>30 символов) -> скорее всего поиск песни по тексту
    if len(message) > 30:
        return "search", message
        
    # Если короткое и без команд -> считаем чатом (лучше ошибиться тут, чем качать мусор)
    return "chat", ""

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение с помощью Gemini.
    Возвращает: (intent, query)
    intent: 'search' | 'radio' | 'chat'
    """
    # Fallback, если AI выключен
    if not HAS_GENAI or not genai:
        logger.debug("NLP Skipped: SDK unavailable (using heuristic)")
        return _heuristic_fallback(message)

    try:
        # ИСПРАВЛЕНИЕ: Используем 'gemini-pro' - самую стабильную модель для этой библиотеки
        model = genai.GenerativeModel("gemini-pro")

        prompt = f"""You are a Music AI Assistant. Analyze this user message: "{message}"

Classify into one of 3 INTENTS:
1. "search" -> Explicit request for a specific song, artist, video (e.g. "play numb", "metallica", "включи цоя").
2. "radio" -> Request for a genre, mood, playlist (e.g. "rock music", "party mix", "давай радио").
3. "chat" -> Conversational messages, greetings, questions (e.g. "hello", "how are you", "quiz", "ну как там?", "привет").

Return JSON ONLY:
{{"intent": "search"|"radio"|"chat", "query": "search query or empty"}}
"""
        response = model.generate_content([prompt])
        text = response.text.strip()
        
        # Чистка JSON
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        
        try:
            result = json.loads(text)
            intent = result.get("intent", "chat") # Default to chat to be safe
            query = result.get("query", message[:100])
            return intent, query
        except json.JSONDecodeError:
            logger.warning(f"[NLP] JSON Parse Error: {text}. Switching to heuristic.")
            return _heuristic_fallback(message)

    except Exception as e:
        logger.warning(f"[NLP] API Error: {e}. Switching to heuristic.")
        return _heuristic_fallback(message)