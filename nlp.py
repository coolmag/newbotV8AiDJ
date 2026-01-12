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

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение с помощью Gemini.
    Возвращает: (intent, query)
    intent: 'search' | 'radio' | 'chat'
    """
    # Fallback, если AI выключен
    if not HAS_GENAI or not genai:
        return "search", message

    try:
        # ИСПРАВЛЕНИЕ: Используем точную версию модели, чтобы избежать 404
        model = genai.GenerativeModel("gemini-1.5-flash-001")

        prompt = f"""Role: Music AI DJ.
Analyze user input: "{message}"

Determine INTENT:
1. "search" -> User wants a specific track, artist, or video.
2. "radio" -> User wants a playlist, vibe, genre, "play something".
3. "chat" -> User is just talking ("hello", "how are you", "who are you", "quiz").

Return ONLY JSON:
{{"intent": "search"|"radio"|"chat", "query": "optimized text"}}

Examples:
"play numb" -> {{"intent": "search", "query": "Linkin Park Numb"}}
"something rock" -> {{"intent": "radio", "query": "best rock hits"}}
"how are you?" -> {{"intent": "chat", "query": ""}}
"privet" -> {{"intent": "chat", "query": ""}}
"""
        response = model.generate_content([prompt])
        text = response.text.strip()
        
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(text)
        intent = result.get("intent", "search")
        query = result.get("query", message[:100])
        
        return intent, query

    except Exception as e:
        logger.warning(f"[NLP] Error: {e}. Fallback to heuristic.")
        # Простейшая эвристика на случай падения AI
        msg_lower = message.lower()
        if len(message) < 10 and not any(x in msg_lower for x in ['play', 'включи', 'найди']):
            # Скорее всего это чат, если сообщение короткое и без команд
            return "chat", ""
        return "search", message
