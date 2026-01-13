import logging
import json
import re
from typing import Tuple, Optional

from gemini_init import generate_smart, HAS_GENAI

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
    
    # === ЭВРИСТИКИ ДЛЯ РАДИО ===
    
    # 0. СПЕЦИАЛЬНЫЕ ПАТТЕРНЫ (до всего остального!)
    # "давай послушаем [жанр/настроение]" -> не как artist detection!
    special_patterns = [
        (r"давай\s+(послушаем\s+)?(советск\w*|советск\w*\s+грув|грув|рок|метал|хип-хоп|рэп|поп|джаз|блюз|электроника|techno|house|chill|lofi|sad|happy|party)", "radio"),
        (r"послушаем\s+(советск\w*|советск\w*\s+грув|грув|рок|метал|хип-хоп|рэп| поп|джаз|блюз|электроника)", "radio"),
        (r"хочу\s+(советск\w*|советск\w*\s+грув|грув|рок|метал|хип-хоп|рэп| поп|джаз|блюз|электроника)", "radio"),
        (r"включи\s+(советск\w*|советск\w*\s+грув|грув|рок|метал|хип-хоп|рэп| поп|джаз|блюз|электроника)", "radio"),
    ]
    
    # Проверяем специальные паттерны для жанров
    if re.search(r"(советск\w*\s*грув|советск\w*|грув)", msg_lower):
        logger.info(f"[NLP] Special pattern: советский грув")
        return "radio", "советский грув"
    
    for p, intent in special_patterns:
        if re.search(p, msg_lower):
            logger.info(f"[NLP] Special pattern matched: {p}")
            # Извлекаем жанр из сообщения
            match = re.search(p, msg_lower)
            if match:
                genre = match.group(2) if match.group(2) else ""
                if genre:
                    return intent, f"{genre} музыка"
            return intent, "популярные треки"
    
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
    # НЕ срабатывает для жанров/настроений!
    artist_patterns = [
        r"(?:давай|включи|поставь|хочу)\s+(?:послушаем\s+)?([а-яёa-z]+)",
    ]
    
    artist_match = re.search(artist_patterns[0], msg_lower)
    if artist_match:
        artist = artist_match.group(1)
        # Проверяем что это не жанр и не слово из исключений
        genre_keywords = ["рок", "метал", "поп", "джаз", "блюз", "грув", "электро", "хип-хоп", "рэп", "реп", "техно", "хаус", "чилл", "лофи", "ло-fi", "чилаут", "сонг", "трек", "песн"]
        if artist and len(artist) > 2 and artist not in EXCLUDE_ARTISTS and artist not in genre_keywords:
            logger.info(f"[NLP] Artist detected: {artist}")
            return "radio", f"{artist} музыка"
    
    # 3. Настроение / режим (проверяем до стандартных паттернов)
    for mood, keywords in RADIO_MOODS.items():
        if any(kw in msg_lower for kw in keywords):
            logger.info(f"[NLP] Mood detected: {mood}")
            return "radio", f"{mood} музыка"
    
    # 4. Команда "радио"
    if "радио" in msg_lower or "волну" in msg_lower:
        query = re.sub(r"(?:радио|волну)\s*", "", msg_lower).strip()
        return "radio", query if query else "популярные треки"
    
    # 5. Стандартные паттерны для поиска (ИСПОЛЬЗУЕТСЯ КАК ФОЛБЭК)
    search_patterns = [r"\bplay\b", r"\bвключи\b", r"\bнайди\b", r"\bиграй\b", r"\bпоставь\b"]
    
    # === AI АНАЛИЗ (основная логика) ===
    if HAS_GENAI:
        try:
            # Сначала пытаемся распознать через AI
            prompt = f"""Analyze message: "{message}"

INTENTS:
1. search (song/artist request like "включи песню", "найди трек")
2. radio (genre/mood/context request like "давай чилл", "включи радио", "вруби что-то под это настроение")
3. chat (conversation)

Return JSON ONLY: {{"intent": "search"|"radio"|"chat", "query": "search query"}}"""

            text = generate_smart(prompt)
            
            if text:
                text = text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text)
                intent = data.get("intent", "chat")
                query = data.get("query", "")
                logger.info(f"[NLP] AI result: intent={intent}, query={query}")
                
                # Если AI решил, что это чат, но есть ключевые слова поиска/радио, 
                # то это может быть ошибкой -> перепроверяем
                is_search_keyword = any(re.search(p, msg_lower) for p in search_patterns)
                if intent == "chat" and is_search_keyword:
                    logger.info("[NLP] AI returned 'chat', but search keywords found. Falling back to simple search.")
                    return "search", message

                if intent == "radio" and not query:
                    query = "популярные треки"
                if intent == "chat" and not query:
                    query = message
                    
                return intent, query

        except Exception as e:
            logger.warning(f"[NLP] AI Error: {e}, falling back to simple patterns.")
            # AI сломался, используем простые правила
    
    # === Фоллбэк на простые правила, если AI недоступен или сломался ===
    
    # Поиск по ключевым словам
    for p in search_patterns:
        if re.search(p, msg_lower):
            return "search", message
            
    # Если ничего не подошло - это чат
    return "chat", message