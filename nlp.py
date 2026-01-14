import logging
import json
import re
from typing import Tuple, Optional
import asyncio

from ai_manager import AIManager

logger = logging.getLogger(__name__)

# === РАДИО ПАТТЕРНЫ ===
RADIO_MOODS = {
    # Медленное / Сон
    "slow": ["медлен", "slow", "релакс", "расслаб", "chill", "lofi", "ambient", "instrumental", "без слов", "пианино"],
    "sleep": ["спать", "уснуть", "сноч", "ночн", "колыбель", "lullaby", "тишина"],
    # Грусть
    "sad": ["груст", "печаль", "тоска", "скука", "вечер", "меланхол"],
    # Веселье / Энергия
    "party": ["весель", "тусовк", "танцевал", "party", "club", "energi", "хайп", "dancing", "энергич"],
    "happy": ["радост", "счаст", "весел", "позитив"],
    # Рок / Метал
    "rock": ["рок", "метал", "hard", "metal", "ария", "кипелов", "король и шут"],
    # Русские хиты
    "russian": ["русск", "советск", "ссср", "наша", "отечеств", "виктор цой", "кино", "любэ", "звери", "би-2"],
}

# Слова для исключения из artist detection
EXCLUDE_ARTISTS = ["что", "такое", "это", "нашу", "наш", "радио", "музыку", "трек", "песню", "включи", "давай", "поставь", "послушаем", "хочу", "мне"]

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    msg_lower = message.lower().strip()
    logger.info(f"[NLP] Analyzing: '{message}' -> '{msg_lower}'")
    
    # === ЭВРИСТИКИ ДЛЯ РАДИО (ВЫСОКИЙ ПРИОРИТЕТ) ===
    
    # Специальные паттерны для жанров
    if re.search(r"(советск\w*\s*грув|советск\w*|грув)", msg_lower):
        logger.info(f"[NLP] Special pattern: советский грув")
        return "radio", "советский грув"

    # "Давай нашу" и похожие
    our_patterns = [r"давай\s+нашу", r"включи\s+нашу", r"поставь\s+нашу", r"нашу\s+музыку", r"наши\s+треки", r"то\s+что\s+слушали", r"похожее", r"в\s+стиле"]
    for p in our_patterns:
        if re.search(p, msg_lower):
            logger.info(f"[NLP] Matched pattern: {p}")
            return "radio", "похожее на то что слушали"
            
    # Настроение / режим
    for mood, keywords in RADIO_MOODS.items():
        if any(kw in msg_lower for kw in keywords):
            logger.info(f"[NLP] Mood detected: {mood}")
            return "radio", f"{mood} музыка"

    # === AI АНАЛИЗ (основная логика) ===
    try:
        prompt = f"""Analyze the user's request for a music bot.

INTENTS:
- "search": Use for a request to find a SPECIFIC, NAMED song or artist. The query MUST contain the name. Examples: "включи Bohemian Rhapsody", "найди трек Rammstein - Sonne".
- "radio": Use for a request to start a music stream based on a GENERAL IDEA, like genre, mood, context, or a vague concept. The query should be the general idea. Examples: "давай чиллвейв", "включи радио 80-х", "вруби что-то под это настроение", "поставь похожее", "удиви меня", "что-то новенькое".
- "chat": Use for a general conversation, question, or greeting that is NOT a request for music. Examples: "привет", "как дела?", "спасибо", "кто ты?".

User's message: "{message}"

Return JSON ONLY.
{{
  "intent": "search" | "radio" | "chat",
  "query": "extracted search query or radio theme"
}}"""

        # Используем новый AIManager для получения ответа от любого провайдера
        text = asyncio.run(AIManager.get_ai_response(prompt))
        
        if text:
            text = text.replace("```json", "").replace("```", "").strip()
            data = json.loads(text)
            intent = data.get("intent", "chat")
            query = data.get("query", "")
            logger.info(f"[NLP] AI result: intent={intent}, query={query}")
            
            if intent == "radio" and not query:
                query = "популярные треки"
            if intent == "chat" and not query:
                query = message
                
            return intent, query

    except Exception as e:
        logger.warning(f"[NLP] AI Error: {e}, falling back to simple patterns.")
        # AI сломался, используем простые правила

    # === ФОЛБЭК НА ПРОСТЫЕ ПРАВИЛА ===
    search_patterns = [r"\bplay\b", r"\bвключи\b", r"\bнайди\b", r"\bиграй\b", r"\bпоставь\b"]
    for p in search_patterns:
        if re.search(p, msg_lower):
            logger.info(f"[NLP] Fallback search pattern matched: {p}")
            return "search", message
            
    if "радио" in msg_lower or "волну" in msg_lower:
        query = re.sub(r"(?:радио|волну)\s*", "", msg_lower).strip()
        logger.info(f"[NLP] Fallback radio pattern matched.")
        return "radio", query if query else "популярные треки"
            
    # Если ничего не подошло - это чат
    logger.info(f"[NLP] Falling back to chat.")
    return "chat", message