import logging
import json
import re
from typing import Tuple, Optional

from gemini_init import generate_smart, HAS_GENAI

logger = logging.getLogger(__name__)

# === РАДИО ПАТТЕРНЫ ===
RADIO_MOODS = {
    # Грусть / Сон
    "sad": ["груст", "печаль", "тоска", "скука", "спать", "снова", "тишина", "уснуть", "ночь", "вечер", "расслаб", "chill", "lofi", "меланхол"],
    "sleep": ["спать", "снова", "уснуть", "ночн", "колыбель", "lullaby"],
    # Веселье / Энергия
    "party": ["весель", "тусовк", "танцевал", "party", "club", "clubbing", "energi", "хайп", "dancing"],
    "happy": ["радост", "счаст", "весел", "позитив"],
    # Рок / Метал
    "rock": ["рок", "метал", "hard", "metal", "rock", "ария", "кипелов", "король и шут"],
    # Русские хиты
    "russian": ["русск", "советск", "ссср", "наша", "отечеств", "виктор цой", "кино", "любэ", "звери", "би-2"],
    # Инструментал
    "instrumental": ["пианино", "гитар", "инструментал", "без слов", "ambient", "nature"],
}

# === НАШИ ТРЕКИ (из истории) ===
# Здесь будем хранить историю запросов пользователей
USER_FAVORITES = {}  # chat_id -> list of artist/title

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    msg_lower = message.lower().strip()
    logger.info(f"[NLP] Analyzing: '{message}' -> '{msg_lower}'")
    
    # === ЭВРИСТИКИ ДЛЯ РАДИО ===
    
    # 1. "Давай нашу" -> включить треки, которые пользователь уже слушал
    our_patterns = [
        r"давай\s+нашу",
        r"включи\s+нашу",
        r"поставь\s+нашу",
        r"нашу\s+музыку",
        r"наши\s+треки",
        r"то\s+что\s+слушали",
        r"похожее",
        r"в\s+стиле",
    ]
    for p in our_patterns:
        if re.search(p, msg_lower):
            logger.info(f"[NLP] Matched pattern: {p}")
            return "radio", "похожее на то что слушали"
    
    # 2. "Давай [исполнитель]" -> включить радио с исполнителем
    artist_match = re.search(r"(?:давай|включи|поставь)\s+([а-яёa-z]+)", msg_lower)
    if artist_match:
        artist = artist_match.group(1)
        if artist and len(artist) > 2:
            exclude = ["спать", "грустить", "веселиться", "нашу", "радио", "музыку", "трек", "песню"]
            if artist not in exclude:
                logger.info(f"[NLP] Artist detected: {artist}")
                return "radio", f"{artist} музыка"
    
    # 3. Настроение / режим
    for mood, keywords in RADIO_MOODS.items():
        if any(kw in msg_lower for kw in keywords):
            logger.info(f"[NLP] Mood detected: {mood}")
            return "radio", f"{mood} музыка"
    
    # 4. Команда "радио"
    if "радио" in msg_lower or "волну" in msg_lower:
        query = re.sub(r"(?:радио|волну)\s*", "", msg_lower).strip()
        return "radio", query if query else "популярные треки"
    
    # 5. Стандартные паттерны для поиска
    search_patterns = [r"\bplay\b", r"\bвключи\b", r"\bнайди\b", r"\bиграй\b", r"\bпоставь\b"]
    for p in search_patterns:
        if re.search(p, msg_lower):
            return "search", message
    
    # Длинное сообщение -> поиск
    if len(message) > 40:
        return "search", message
    
    # === AI АНАЛИЗ ===
    if not HAS_GENAI: 
        return "chat", ""

    try:
        prompt = f"""Analyze message: "{message}"

INTENTS:
1. search (song/artist request like "включи песню", "найди трек")
2. radio (genre/mood request like "давай чилл", "включи радио", "давай Арию")
3. chat (conversation)

Return JSON ONLY: {{"intent": "search"|"radio"|"chat", "query": "search query"}}"""

        text = generate_smart(prompt)
        
        if not text:
            return "chat", ""
            
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        intent = data.get("intent", "chat")
        query = data.get("query", "")
        logger.info(f"[NLP] AI result: intent={intent}, query={query}")
        
        if intent == "radio" and not query:
            query = "популярные треки"
            
        return intent, query

    except Exception as e:
        logger.warning(f"[NLP] Error: {e}")
        return "chat", ""