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
        # Пробуем универсальную модель
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""Analyze: "{message}"

JSON: {{"intent": "search"|"radio"|"chat", "query": "text"}}"""
        
        response = model.generate_content([prompt])
        text = response.text.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(text)
        return data.get("intent", "chat"), data.get("query", message[:100])

    except Exception as e:
        logger.warning(f"NLP Error: {e}")
        return _heuristic_fallback(message)
