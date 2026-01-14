import logging
import json
import re
from typing import Tuple, Optional
import asyncio

from ai_manager import AIManager

logger = logging.getLogger(__name__)

async def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение пользователя с помощью AI для определения намерения и формирования поискового запроса.
    Эта функция теперь полностью асинхронна.
    """
    msg_lower = message.lower().strip()
    logger.info(f"[NLP] Analyzing with AI: '{message}'")

    # Улучшенный промпт для AI
    prompt = f"""You are a music expert AI inside a Telegram bot. Your task is to analyze the user's message and convert it into a precise search query for YouTube Music.

Analyze the user's message to identify:
- Genre (e.g., rock, pop, classic)
- Sub-genre (e.g., death metal, synth-pop)
- Era/Decade (e.g., 80s, 90s, 2020s)
- Language/Nationality (e.g., russian, french, soviet)
- Mood (e.g., energetic, sad, for training)
- Specific artist or song if mentioned.

Combine these elements into a single, effective search query string.

The user's message is: "{message}"

Return a JSON object with two fields:
1. "intent":
   - "radio": If the user wants a playlist, stream, or music based on a theme/genre/mood. The 'query' will be your generated YouTube search string.
   - "search": If the user wants ONE specific track or artist. The 'query' will be the name of that track/artist.
   - "chat": If it's a general conversation, greeting, or question not about music.

2. "query": Your generated search query or the original message for 'chat'.

Example 1:
User's message: "привет давай русский рок из 90х"
Your output:
{{
  "intent": "radio",
  "query": "русский рок 90-х"
}}

Example 2:
User's message: "что-то энергичное для тренировки"
Your output:
{{
  "intent": "radio",
  "query": "energetic music for workout"
}}

Example 3:
User's message: "поставь queen bohemian rhapsody"
Your output:
{{
  "intent": "search",
  "query": "Queen Bohemian Rhapsody"
}}

Example 4:
User's message: "как дела?"
Your output:
{{
  "intent": "chat",
  "query": "как дела?"
}}

Now, analyze this message:
User's message: "{message}"

Return JSON ONLY.
"""

    try:
        # Прямой асинхронный вызов AIManager
        text = await AIManager.get_ai_response(prompt)
        
        if text:
            # Очистка и парсинг JSON
            text = re.sub(r"```json\s*|\s*```", "", text).strip()
            data = json.loads(text)
            intent = data.get("intent", "chat")
            query = data.get("query", "")
            
            logger.info(f"[NLP] AI result: intent={intent}, query='{query}'")
            
            # Фоллбэк, если AI вернул пустой query
            if not query:
                if intent == "radio":
                    query = "популярные треки"
                else: # chat или search
                    query = message
            
            return intent, query

    except Exception as e:
        logger.warning(f"[NLP] AI Error: {e}, falling back to simple patterns.")
        # AI сломался, используем старые простые правила как фоллбэк

    # === ФОЛЛБЭК НА ПРОСТЫЕ ПРАВИЛА (если AI не сработал) ===
    search_patterns = [r"\bplay\b", r"\bвключи\b", r"\bнайди\b", r"\bиграй\b", r"\bпоставь\b"]
    if any(re.search(p, msg_lower) for p in search_patterns):
        logger.info(f"[NLP] Fallback search pattern matched.")
        # Просто вырезаем команду, оставляем остальное как запрос
        query = re.sub(r"|".join(search_patterns), "", msg_lower, flags=re.IGNORECASE).strip()
        return "search", query if query else message
            
    if "радио" in msg_lower or "волну" in msg_lower:
        query = re.sub(r"(?:радио|волну)\s*", "", msg_lower).strip()
        logger.info(f"[NLP] Fallback radio pattern matched.")
        return "radio", query if query else "популярные треки"
            
    # Если ничего не подошло - это чат
    logger.info(f"[NLP] Falling back to chat.")
    return "chat", message