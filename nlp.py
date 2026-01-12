import logging
import json
from typing import Tuple, Optional, Any

# Импорты будут переданы через аргументы
# from google import genai
# from main import HAS_GENAI, GEMINI_KEY 

from config import Settings # Still needed for other configs, even if not for GEMINI_API_KEY check

logger = logging.getLogger(__name__)

def analyze_message(message: str, genai_module: Any, has_genai: bool, gemini_key: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение с помощью Gemini (синхронно).
    Использует переданный модуль genai и его флаги.
    """
    if not has_genai or genai_module is None or not gemini_key:
        logger.warning("SDK genai не доступен или ключ отсутствует → fallback на search")
        return "search", message

    try:
        model = genai_module.GenerativeModel("gemini-1.5-flash")

        prompt = f"""Ты — музыкальный AI-диджей.
Анализируй сообщение пользователя: "{message}"

Определи интент:
- "search" — хочет конкретный трек, артиста или песню
- "radio" — хочет микс, жанр, вайб, "давай", "включи", "кайф", "движение"

Верни ТОЛЬКО чистый JSON без markdown, комментариев и лишних слов:
{{"intent": "search"|"radio", "query": "короткий точный запрос для YouTube"}}

Примеры:
"давай давай" → {{"intent": "radio", "query": "энергичные русские хиты"}}
"кайф" → {{"intent": "radio", "query": "кайфовая музыка"}}
"что нового?" → {{"intent": "search", "query": "новинки музыки 2026"}}
"ясно" → {{"intent": "radio", "query": "chill вайб"}}
"""

        response = model.generate_content([prompt])

        text = response.text.strip()
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0].strip()

        result = json.loads(text)
        intent = result.get("intent", "search")
        query = result.get("query", message[:150])

        logger.info(f"[Gemini] '{message}' → intent={intent}, query='{query}'")
        return intent, query

    except Exception as e:
        logger.error(f"Gemini ошибка: {str(e)[:300]}")
        return "search", message[:150]
